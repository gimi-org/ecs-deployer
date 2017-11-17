from setuptools import setup


setup(
    name="ecs-deployer",
    version="0.1.1",
    packages=["ecs_deployer"],
    author="Andy Sun",
    author_email="andy_sun_sha@hotmail.com",
    license='MIT',
    url='https://github.com/AndySun25/ecs-deployer',
    description="Simple Python ECS deployment script.",
    scripts=["ecs_deployer/bin/ecs-deployer.py"],
    install_requires=[
        'boto3>=1.4.6'
    ],
    python_requires='>3.5',
)
