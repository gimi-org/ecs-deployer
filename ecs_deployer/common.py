import logging
import re
import subprocess
import boto3

logger = logging.getLogger()
ecs_client = boto3.client('ecs')


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

    def __str__(self) -> str:
        return "<Docker Image> - {}".format(self.name)


class TaskDefinition:
    def __init__(self, name, config) -> None:
        self.name = name
        self.config = config

    @property
    def deregister_previous_definitions(self) -> bool:
        return self.config.get('deregisterPreviousDefinitions', True)

    @property
    def family(self) -> str:
        return self.config['family']

    @property
    def task_role_arn(self) -> str:
        return self.config.get('taskRoleARN')

    @property
    def network_mode(self) -> str:
        return self.config.get('networkMode', 'bridge')

    @property
    def container_definitions(self) -> list:
        return self.config['containerDefinitions']

    @property
    def volumes(self) -> list:
        return self.config.get('volumes', [])

    @property
    def placement_constraints(self) -> list:
        return self.config.get('placementConstraints', [])

    def set_images(self, images) -> None:
        for container_def in self.container_definitions:
            container_def['image'] = images[container_def['image']]

    def deregister_existing_definitions(self) -> None:
        definitions = ecs_client.list_task_definitions(familyPrefix=self.family)['taskDefinitionArns']

        for definition in definitions:
            ecs_client.deregister_task_definition(taskDefinition=definition)

    def register(self) -> str:
        result = ecs_client.register_task_definition(
            family=self.family,
            taskRoleARN=self.task_role_arn,
            networkMode=self.network_mode,
            containerDefinitions=self.container_definitions,
            volumes=self.volumes,
            placementConstraints=self.placement_constraints,
        )

        return '{}:{}'.format(self.family, result['taskDefinition']['revision'])

    def handle(self) -> str:
        if self.deregister_previous_definitions:
            self.deregister_existing_definitions()
        return self.register()

    def __str__(self) -> str:
        return "<TaskDefinition> - {}".format(self.name)


class Task:
    def __init__(self, name, config) -> None:
        self.name = name
        self.config = config

    def run(self):
        ecs_client.run_task(**self.config)

    def handle(self):
        self.run()

    def __str__(self) -> str:
        return "<Task> - {}".format(self.name)


class Service:
    def __init__(self, name, config) -> None:
        self.name = name
        self.config = config

    @property
    def cluster(self):
        return self.config['cluster']

    def update(self) -> None:
        services = ecs_client.list_services(cluster=self.cluster)['serviceArns']

        for service in [s for s in services if re.match(
                r'arn:aws:ecs:[^:]+:[^:]+:service/{}'.format(self.name), s)]:
            ecs_client.update_service(
                service=service,
                **self.config
            )

    def handle(self):
        self.update()

    def __str__(self) -> str:
        return "<Service> - {}".format(self.name)


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


def docker_login() -> None:
    cmd = run_command(['aws', 'ecr', 'get-login', '--no-include-email']).rstrip('\n').split(' ')
    run_command(cmd)
