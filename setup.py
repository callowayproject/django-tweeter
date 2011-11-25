#!/usr/bin/env python
from setuptools import setup

setup(
    name='django-oauth-twitter',
    version='1.11',
    description=('A Django application that lets you associate Twitter '
                 'accounts with your User accounts'),
    long_description=(
"""
Features include:

* Uses django.contrib.auth.User
* Lets Twitter users sign in before registering.
* Optional auto-creation of Users from Twitter screen-names
* Lets Users link and unlink Twitter accounts.
* Uses Django cache framework for caching results.
"""
    ),
    author='Akoha Inc.',
    author_email='adminmail@akoha.com',
    url='http://bitbucket.org/akoha/django-oauth-twitter/',
    packages=['django_oauth_twitter', 'django_oauth_twitter.migrations'],
    package_data={
        'django_oauth_twitter': ['templates/django_oauth_twitter/*.html'],
    },
    requires=['oauth', 'oauth_python_twitter'],
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Web Environment',
        'Framework :: Django',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
    ],
    zip_safe=True,
)
