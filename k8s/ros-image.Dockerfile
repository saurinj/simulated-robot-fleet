# ROS image for the fleet simulator AND the Kafka bridge.
# One image, two entrypoints (see fleet.yaml and bridge.yaml).
#
# Build from the project root:
#   docker build -t fleet-ros:latest -f k8s/ros-image.Dockerfile .
FROM osrf/ros:humble-desktop

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --no-cache-dir kafka-python prometheus_client

WORKDIR /opt/fleet_ws
COPY fleet_ws/src ./src
RUN /bin/bash -c "source /opt/ros/humble/setup.bash && colcon build"
