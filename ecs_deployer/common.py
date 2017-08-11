import json
import logging
import re
import subprocess
import tempfile

logger = logging.getLogger()


class DockerImage:
    def __init__(self, name, dockerfile, tagCommand, repository, build) -> None:
        self.name = name
        self.dockerfile = dockerfile
        self.tag_command = tagCommand
        self.repository = repository
        self.build = build

    @property
    def tag(self) -> str:
        try:
            return self._tag
        except AttributeError:
            self._tag = run_command(self.tag_command, shell=True).strip()
            return self._tag

    @property
    def tagged_name(self) -> str:
        return '{}:{}'.format(self.name, self.tag)

    @property
    def tagged_repo_name(self) -> str:
        return '{}:{}'.format(self.repository, self.tag)

    def build_image(self) -> None:
        run_command(['docker', 'build', '-t', self.tagged_name, '-f', self.dockerfile, '.'])
        run_command(['docker', 'tag', self.tagged_name, self.tagged_repo_name])

    def tag_image(self) -> None:
        run_command(['docker', 'tag', self.name, self.tagged_repo_name])

    def push(self) -> None:
        run_command(['docker', 'push', self.tagged_repo_name])

    def handle(self) -> str:
        if self.build:
            self.build_image()
        else:
            self.tag_image()

        self.push()
        return self.tagged_repo_name


class TaskDefinition:
    def __init__(self, config) -> None:
        self.config = config

    @property
    def task_family(self):
        return self.config['family']

    def set_images(self, images):
        for container_def in self.config['containerDefinitions']:
            container_def['image'] = images[container_def['image']]

    def deregister_existing_definitions(self) -> None:
        definitions = run_ecs_command(['list-task-definitions', '--family', self.task_family]
                                      )['taskDefinitionArns']

        for definition in definitions:
            run_ecs_command(['deregister-task-definition', '--task-definition', definition])

    def register(self) -> str:
        with tempfile.NamedTemporaryFile(mode='wt', suffix='.json') as f:
            task_def_str = json.dumps(self.config)
            f.write(task_def_str)
            f.flush()
            result = run_ecs_command(['register-task-definition', '--cli-input-json', 'file://{}'.format(f.name)])

        return '{}:{}'.format(self.task_family, result['taskDefinition']['revision'])

    def handle(self) -> str:
        self.deregister_existing_definitions()
        return self.register()


class Task:
    def __init__(self, clusterName, taskDefinition, count) -> None:
        self.cluster_name = clusterName
        self.task_def = taskDefinition
        self.count = count

    def set_task_definition(self, definitions):
        self.task_definition = definitions[self.task_def]

    def run(self):
        run_ecs_command(['run-task', '--cluster', self.cluster_name, '--task-definition',
                         self.task_definition, '--count', str(self.count)])

    def handle(self):
        self.run()


class Service:
    def __init__(self, name, clusterName, taskDefinition) -> None:
        self.name = name
        self.cluster_name = clusterName
        self.task_def = taskDefinition

    def set_task_definition(self, definitions):
        self.task_definition = definitions[self.task_def]

    def update(self):
        services = run_ecs_command(['list-services', '--cluster', self.cluster_name])['serviceArns']
        for service in [s for s in services if re.match(
                r'arn:aws:ecs:[^:]+:[^:]+:service/{}'.format(self.name), s)]:
            run_ecs_command(['update-service', '--service', service, '--task-definition',
                             self.task_definition, '--cluster', self.cluster_name])

    def handle(self):
        self.update()


def run_command(command, ignore_error=False, **kwargs) -> str:
    """f
    :param command: Command as string or tuple of args.
    :param ignore_error: Fail silently.
    :return:
    """
    if not isinstance(command, (list, tuple)):
        command = (command,)
    logger.info('Running command: %s', ' '.join(command))
    print('Running command: %s' % ' '.join(command))

    try:
        stdout = subprocess.check_output(command, **kwargs)
        return stdout.decode()
    except subprocess.CalledProcessError as e:
        if not ignore_error:
            logger.error('Command failed: %s', str(e))
            raise


def run_ecs_command(args, **kwargs) -> dict:
    return json.loads(run_command(['aws', 'ecs'] + args, **kwargs))


def docker_login() -> None:
    cmd = run_command(['aws', 'ecr', 'get-login', '--no-include-email']).rstrip('\n').split(' ')
    run_command(cmd)
