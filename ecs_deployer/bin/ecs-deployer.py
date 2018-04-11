#!/usr/bin/env python3
# flake8: noqa
import argparse
from json import JSONDecodeError
from botocore.exceptions import ClientError

import boto3
import json
import logging
import os
import subprocess
import requests

import sys

logger = logging.getLogger()
ecs_client = boto3.client('ecs')
ecr_client = boto3.client('ecr')
webhook_url = os.environ.get('ECS_DEPLOYER_WEBHOOK_URL')


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

    def delete_local(self) -> None:
        run_command(['docker', 'rmi', self.tagged_name])

    def handle(self, keep_image, force_push_image) -> str:
        try:
            response = ecr_client.describe_images(repositoryName=self.repository.split('/')[1], imageIds=[{'imageTag': self.tag}])
            image_exists = len(response['imageDetails'])
        except ClientError:
            image_exists = False

        if not image_exists or force_push_image:
            if self.build:
                self.build_image()
            else:
                self.tag_image()
            self.push()

            if self.build and not keep_image:
                self.delete_local()
        else:
            print("Image {} exists, skipping.".format(self.tagged_repo_name))
        return self.tagged_repo_name

    def __str__(self) -> str:
        return "<Docker Image> - {}".format(self.name)


class TaskDefinition:
    def __init__(self, name, config) -> None:
        self.name = name
        self.config = config
        self.revision = None

    @property
    def deregister_previous_definitions(self) -> bool:
        return self.config.get('deregisterPreviousDefinitions', True)

    @property
    def family(self) -> str:
        return self.config['family']

    @property
    def task_role_arn(self) -> str:
        return self.config.get('taskRoleArn')

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

    def update_environment(self, envs) -> None:
        json_envs = [{"name": key, "value": value} for key, value in envs.items()]
        for container_def in self.container_definitions:
            container_def['environment'] += json_envs

    def set_images(self, images) -> None:
        for container_def in self.container_definitions:
            container_def['image'] = images[container_def['image']]

    def deregister_existing_definitions(self) -> None:
        if not self.revision:
            return
        definitions = ecs_client.list_task_definitions(familyPrefix=self.family)['taskDefinitionArns']

        for definition in definitions:
            if definition.split(':')[-1] != str(self.revision):
                ecs_client.deregister_task_definition(taskDefinition=definition)

    def register(self) -> str:
        print("Registering task definition: '{}'".format(self.family))
        result = ecs_client.register_task_definition(
            family=self.family,
            taskRoleArn=self.task_role_arn,
            networkMode=self.network_mode,
            containerDefinitions=self.container_definitions,
            volumes=self.volumes,
            placementConstraints=self.placement_constraints,
        )
        self.revision = result['taskDefinition']['revision']

        return '{}:{}'.format(self.family, self.revision)

    def deregister(self) -> None:
        if self.revision is not None:
            ecs_client.deregister_task_definition(taskDefinition='{}:{}'.format(self.family, self.revision))

    def __str__(self) -> str:
        return "<TaskDefinition> - {}".format(self.name)


class Task:
    def __init__(self, name, config) -> None:
        self.name = name
        self.config = config

    def run(self):
        print("Running task: '{}'".format(self.name))
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
        print("Updating service: '{}'".format(self.name))
        ecs_client.update_service(service=self.name, **self.config)

    def handle(self):
        self.update()

    def __str__(self) -> str:
        return "<Service> - {}".format(self.name)


def run_command(command, ignore_error=False, silent=False, **kwargs) -> str:
    """f
    :param command: Command as string or tuple of args.
    :param ignore_error: Fail silently.
    :param silent: Do not log command execution.
    :return:
    """
    if not isinstance(command, (list, tuple)):
        command = (command,)

    if not silent:
        print('Running command: %s' % ' '.join(command))

    try:
        stdout = subprocess.check_output(command, **kwargs)
        return stdout.decode()
    except subprocess.CalledProcessError as e:
        if not ignore_error:
            print('Command failed: %s', str(e), file=sys.stderr)
            raise


def docker_login() -> None:
    cmd = run_command(['aws', 'ecr', 'get-login', '--no-include-email']).rstrip('\n').split(' ')
    run_command(cmd)


def get_json(file_path, fail_silently=False):
    try:
        with open(file_path, 'rt') as f:
            return json.loads(f.read())
    except:
        if fail_silently:
            return {}
        else:
            raise


def verify_config_files(config_dir):
    config_data = {}
    skipped_files = []
    invalid_files = []

    for conf_type in ('images', 'task_definitions', 'tasks', 'services', 'envs'):
        try:
            config_data[conf_type] = get_json(os.path.join(config_dir, '{}.json'.format(conf_type)))
        except FileNotFoundError:
            config_data[conf_type] = {}
            skipped_files.append(conf_type)
        except JSONDecodeError:
            invalid_files.append(conf_type)

    if skipped_files:
        logger.warning("Config files skipped (not found): {}".format(skipped_files))
    if invalid_files:
        raise ValueError("Invalid configuration files: {}".format(invalid_files))

    return config_data


def send_webhook_message(config_dir, success):
    if webhook_url is not None:
        if success:
            text = "Successfully deployed configuration `{}`.".format(config_dir)
            color = 'good'
        else:
            text = "Failed to deploy configuration `{}`.".format(config_dir)
            color = 'danger'

        try:
            tag, message = run_command(['git', 'log', '--oneline', '-1'], silent=True).strip().split(" ", 1)
            text += '\n`{}` {}'.format(tag, message)
        except:
            pass

        data = {'attachments': [
            {
                'fallback': text,
                'color': color,
                'text': text,
                'mrkdwn_in': ['text']
            }
        ]}
        requests.post(webhook_url, data=json.dumps(data), headers={'Content-Type': 'application/json'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Build and/or deploy Docker image to specified repo and update services/task definitions.")
    parser.add_argument('env', help='Path to config directory')
    parser.add_argument('-f', '--force-push-image', action='store_true', help='Push image even if tag exists in ecr.')
    parser.add_argument('-k', '--keep-image', action='store_true', help='Keep dockers image after pushing.')
    parser.add_argument('--skip-stash', action='store_true', help='Keep dockers image after pushing.')
    args = parser.parse_args()

    stashed = False
    if not args.skip_stash:
        # Stash changes so the deploy actually sends out correct code.
        try:
            stashed = run_command(['git', 'stash']).strip() != 'No local changes to save'
        except subprocess.CalledProcessError:
            pass

    config_dir = os.path.abspath(args.env)
    config_data = verify_config_files(config_dir)
    success = False

    try:
        docker_images = {}
        updated_task_definitions = []

        docker_login()

        # Handling docker containers based on config file.
        print("\nPreparing docker images...")
        for name, image_config in config_data['images'].items():
            image = DockerImage(name, **image_config)
            docker_images[name] = image.handle(args.keep_image, args.force_push_image)

        try:
            # Handling task definitions based on config file.
            print("\nUpdating task definitions...")
            for name, task_def_config in config_data['task_definitions'].items():
                task_def = TaskDefinition(name, task_def_config)
                task_def.update_environment(config_data['envs'])
                task_def.set_images(docker_images)
                task_def.register()
                updated_task_definitions.append(task_def)
        except:
            print("\nError updating task definitions, deregistering!")
            for task_def in updated_task_definitions:
                task_def.deregister()
        else:
            for task_def in updated_task_definitions:
                task_def.deregister_existing_definitions()

            # Handling one-time tasks
            print("\nRunning one-time tasks...")
            for name, task_config in config_data['tasks'].items():
                task_def = Task(name, task_config)
                try:
                    task_def.handle()
                except Exception as e:
                    logger.warning("Unable to run task {name}: {error}".format(name=name, error=str(e)))

            # Handling services based on config file
            print("\nUpdating services...")
            for name, service_config in config_data['services'].items():
                service = Service(name, service_config)
                service.handle()

            success = True
    finally:
        if stashed:
            run_command(['git', 'stash', 'pop'])
        send_webhook_message(args.env, success)
