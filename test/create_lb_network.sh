#!/bin/sh

# Create network for the loadbalancer
docker network create -d overlay loadbalancer --subnet 11.0.0.0/22