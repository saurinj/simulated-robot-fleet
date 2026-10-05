from setuptools import find_packages, setup

package_name = 'fleet_bridge'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', ['launch/bridge.launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Saurin',
    maintainer_email='saurin@example.com',
    description='Forwards fleet telemetry from ROS 2 to Kafka',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'bridge_node = fleet_bridge.bridge_node:main',
        ],
    },
)
