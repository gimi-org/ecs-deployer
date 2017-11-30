A simple python script for deploying to Amazon ECS that does the following.

1. Build and/or tag your docker image(s).
2. Update existing task definitions.
3. Runs one-time tasks.
4. Update services with new task definition references.

AWS credentials must be available as environment variables.
Uses awscli package to call required functions.

Python 3.5+ required.