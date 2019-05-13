#!/bin/bash

TAG=$(git log -1 --pretty=%H)

REPOSITORY=rnzdocker1/eks-elastic-inference-app

docker build --tag $REPOSITORY:$TAG .

docker push $REPOSITORY:$TAG
