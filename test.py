import boto3
import os
import sys
import requests
import json

import coco_label_map

ENDPOINT = 'http://localhost:8501/v1/models/default:predict'
TMP_FILE = './tmp.mov'

def get_prediction_from_image_array(image_array):
    payload = {"instances": [image_array.tolist()]}
    res = requests.post(ENDPOINT, json=payload)
    return res.json()['predictions'][0]

def get_classes_with_scores(predictions):
    num_detections = int(predictions['num_detections'])
    detected_classes = predictions['detection_classes'][:num_detections]
    detected_classes =[coco_label_map.label_map[int(x)] for x in detected_classes]
    detection_scores = predictions['detection_scores'][:num_detections]
    return list(zip(detected_classes, detection_scores))

def process_video_from_file(file_path):
    frames = []
    vidcap = cv2.VideoCapture(file_path)
    success, frame = vidcap.read()
    success = True
    while success:
      frames.append(frame)
      success, frame = vidcap.read()

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
        print('Please set the environment variables for SQS_TASK_QUEUE and SQS_TASK_COMPLETED_QUEUE')
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

    print('Instance initialized: ' + instance_id)

    while True:
        for message in task_queue.receive_messages(WaitTimeSeconds=20):
            try:
                print('Message received - instance: ' + instance_id)

                ec2.modify_instance_attribute(
                    InstanceId=instance_id,
                    DisableApiTermination={ 'Value': True },
                )
                print('Termination protection engaged - instance: ' + instance_id)

                message.change_visibility(VisibilityTimeout=600)
                print('Message visibility updated - instance: ' + instance_id)

                # Process the message
                doc = json.loads(message.body)

                s3.download_file(doc['bucket'], dock['object'], TMP_FILE)

                predictions_for_frames = process_video_from_file(TMP_FILE)

                task_completed_queue.send_message(MessageBody=''.join(e for e in predictions_for_frames))
                print('Task completed msg sent - instance: ' + instance_id)
                message.delete()
                print('Message deleted - instance: ' + instance_id)

                ec2.modify_instance_attribute(
                    InstanceId=instance_id,
                    DisableApiTermination={ 'Value': False },
                )
                print('Termination protection disengaged - instance: ' + instance_id)

                if os.path.exists(TMP_FILE):
                    os.remove(TMP_FILE)

            except:
                print('Problem processing message', sys.exc_info()[0])

if __name__ == '__main__':
    main()
