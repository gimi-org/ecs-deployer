from setuptools import setup


setup(
    name="ecs-deployer",
    version="0.0.1",
    packages=["ecs_deployer"],
    author="Andy Sun",
    author_email="andy_sun_sha@hotmail.com",
    description="Simple Python ECS deployment script.",
    scripts=["ecs_deployer/bin/ecs-deploy.py"],
    install_requires=[
        'awscli>=1.11.106'
    ],
    python_requires='>3.5',
)
