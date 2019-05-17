import boto3
import os
import sys
import cv2
import numpy
import requests
import json
import logging

import coco_label_map

ENDPOINT = 'http://localhost:8501/v1/models/default:predict'
TMP_FILE = "./tmp.mov"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s',
    handlers=[ logging.StreamHandler(sys.stdout) ],
)

log = logging.getLogger()

def get_prediction_from_image_array(image_array):
    log.info('get_prediction_from_image_array')

    payload = {"instances": [image_array.tolist()]}
    log.info('get_prediction_from_image_array  before endpoint call')
    res = requests.post(ENDPOINT, json=payload)
    log.info('get_prediction_from_image_array  after endpoint call')
    return res.json()['predictions'][0]

def get_classes_with_scores(predictions):
    num_detections = int(predictions['num_detections'])
    detected_classes = predictions['detection_classes'][:num_detections]
    detected_classes =[coco_label_map.label_map[int(x)] for x in detected_classes]
    detection_scores = predictions['detection_scores'][:num_detections]
    return list(zip(detected_classes, detection_scores))

def process_video_from_file(file_path, instance_id):

    log.info('Start processing video - instance: %s', instance_id)

    frames = []
    vidcap = cv2.VideoCapture(file_path)
    success, frame = vidcap.read()
    success = True

    log.info('processing video first loop - instance: %s', instance_id)
    count = 0
    while success:
        if count % 100 == 0:
            log.info('frame: %d', count)

        count += 1
        frames.append(frame)
        success, frame = vidcap.read()

    log.info('processing video second loop - instance: %s', instance_id)
    pred_list = []
    for frame in frames:
        preds = get_prediction_from_image_array(frame)
        classes_with_scores = get_classes_with_scores(preds)
        pred_list.append(str(classes_with_scores))
        pred_list.append('\n')

    return pred_list

def main():

    task_queue_name = None
    task_completed_queue_name = None

    try:
        task_queue_name = os.environ['SQS_TASK_QUEUE']
        task_completed_queue_name = os.environ['SQS_TASK_COMPLETED_QUEUE']
    except KeyError:
        log.error('Please set the environment variables for SQS_TASK_QUEUE and SQS_TASK_COMPLETED_QUEUE')
        sys.exit(1)

    # Get the instance information
    r = requests.get("http://169.254.169.254/latest/dynamic/instance-identity/document")
    r.raise_for_status()
    response_json = r.json()
    region = response_json.get('region')
    instance_id = response_json.get('instanceId')

    ec2 = boto3.client('ec2', region_name=region)
    s3 = boto3.client('s3', region_name=region)

    task_queue = boto3.resource('sqs', region_name=region).get_queue_by_name(QueueName=task_queue_name)
    task_completed_queue = boto3.resource('sqs', region_name=region).get_queue_by_name(QueueName=task_completed_queue_name)

    log.info('Initialized - instance: %s', instance_id)

    while True:
        for message in task_queue.receive_messages(WaitTimeSeconds=20):
            try:
                log.info('Message received - instance: %s', instance_id)

                ec2.modify_instance_attribute(
                    InstanceId=instance_id,
                    DisableApiTermination={ 'Value': True },
                )
                log.info('Termination protection engaged - instance: %s', instance_id)

                message.change_visibility(VisibilityTimeout=600)
                log.info('Message visibility updated - instance: %s', instance_id)

                log.info('before message body print')
                log.info('%s', message.body)

                # Process the message
                doc = json.loads(message.body)
                log.info('Message body is loaded - instance: %s', instance_id)

                s3.download_file(doc['bucket'], doc['object'], TMP_FILE)
                log.info('File is downloaded - instance: %s', instance_id)

                log.info('Starting predictions - instance: %s', instance_id)
                predictions_for_frames = process_video_from_file(TMP_FILE, instance_id)
                log.info('Predictions completed - instance: %s', instance_id)

                task_completed_queue.send_message(MessageBody=''.join(e for e in predictions_for_frames))
                log.info('Task completed msg sent - instance: %s', instance_id)
                message.delete()
                log.info('Message deleted - instance: %s', instance_id)

                ec2.modify_instance_attribute(
                    InstanceId=instance_id,
                    DisableApiTermination={ 'Value': False },
                )
                log.info('Termination protection disengaged - instance: %s', instance_id)

                if os.path.exists(TMP_FILE):
                    os.remove(TMP_FILE)

            except:
                log.error('Problem processing message: %s - instance: %s', sys.exc_info()[0], instance_id)

if __name__ == '__main__':
    main()

