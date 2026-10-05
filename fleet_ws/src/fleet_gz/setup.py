from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'fleet_gz'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'worlds'), glob('worlds/*.sdf')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Saurin',
    maintainer_email='joshi.saurin@gmail.com',
    description='Project 2 starter: headless Gazebo Fortress simulation bridged to ROS 2.',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'drive_test = fleet_gz.drive_test:main',
            'odom_tf_relay = fleet_gz.odom_tf_relay:main',
        ],
    },
)
