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

FRAME_BATCH=50

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s',
    handlers=[ logging.StreamHandler(sys.stdout) ],
)

log = logging.getLogger()

def get_predictions_from_image_array(batch):
    log.info('get_predictions_from_image_array')
    res = requests.post(ENDPOINT, json={ 'instances': batch })
    return res.json()['predictions']

def get_classes_with_scores(predictions):
    log.info('get_classes_with_scores')

    vals = []

    for p in predictions:
        log.info('prediction')
        num_detections = int(p['num_detections'])
        log.info('num_detections')
        detected_classes = p['detection_classes'][:num_detections]
        log.info('detection_classes')
        detected_classes =[coco_label_map.label_map[int(x)] for x in detected_classes]
        log.info('get label')
        detection_scores = p['detection_scores'][:num_detections]
        log.info('detection_scores')
        vals.append(list(zip(detected_classes, detection_scores)))

    return vals

def process_video_from_file(file_path):

    log.info('process_video_from_file')

    frames = []
    vidcap = cv2.VideoCapture(file_path)
    success, frame = vidcap.read()
    success = True

    log.info('start frame extraction')

    while success:
        frames.append(frame)
        success, frame = vidcap.read()

    log.info('end frame extraction')

    count = len(frames)

    log.info('frame count: %d', count)
    batch = []
    predictions = []

    for i in range(count):
        log.info('range: %d', i)
        if len(batch) == FRAME_BATCH or i == (count - 1):
            log.info('start batch process')

            for v in get_classes_with_scores(get_predictions_from_image_array(batch)):
                log.info('batch process result')
                predictions.append(str(v))
                predictions.append('\n')
            batch.clear()
        else:
            batch.append(frames[i].tolist())

    vidcap.release()
    cv2.destroyAllWindows()

    return predictions

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
        for message in task_queue.receive_messages(WaitTimeSeconds=10):
            try:
                log.info('Message received - instance: %s', instance_id)

                ec2.modify_instance_attribute(
                    InstanceId=instance_id,
                    DisableApiTermination={ 'Value': True },
                )
                log.info('Termination protection engaged - instance: %s', instance_id)

                message.change_visibility(VisibilityTimeout=600)
                log.info('Message visibility updated - instance: %s', instance_id)

                # Process the message
                doc = json.loads(message.body)
                log.info('Message body is loaded - instance: %s', instance_id)

                s3.download_file(doc['bucket'], doc['object'], TMP_FILE)
                log.info('File is downloaded - instance: %s', instance_id)

                log.info('Starting predictions - instance: %s', instance_id)
                predictions_for_frames = process_video_from_file(TMP_FILE)
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

