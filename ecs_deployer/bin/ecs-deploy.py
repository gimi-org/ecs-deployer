#!/usr/bin/env python3
import argparse
import json
import logging
import os

from ecs_deployer.common import DockerImage, TaskDefinition, Service, docker_login, Task

logger = logging.getLogger()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Build and/or deploy Docker image to specified repo and update services/task definitions.")
    parser.add_argument('config', help='Your config JSON file')
    args = parser.parse_args()

    config_path = os.path.abspath(args.config)

    with open(config_path, 'rt') as f:
        config = json.loads(f.read())

    docker_images = {}
    task_definitions = {}

    docker_login()

    # Handling docker containers based on config file.
    logger.info("Preparing docker images...")
    for name, image_config in config['dockerImages'].items():
        image = DockerImage(name, **image_config)
        docker_images[name] = image.handle()

    # Handling task definitions based on config file.
    logger.info("Updating task definitions...")
    for name, task_def_config in config['taskDefinitions'].items():
        task_def = TaskDefinition(task_def_config)
        task_def.set_images(docker_images)
        task_definitions[name] = task_def.handle()

    # Handling one-time tasks
    logger.info("Running one-time tasks...")
    for name, task_config in config['tasks'].items():
        task_def = Task(**task_config)
        task_def.set_task_definition(task_definitions)
        task_def.handle()

    # Handling services based on config file
    logger.info("Updating services...")
    for name, service_def in config['services'].items():
        service = Service(name, **service_def)
        service.set_task_definition(task_definitions)
        service.handle()
