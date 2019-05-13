import boto3, os, sys, requests


def main():

    task_queue_name = None
    task_completed_queue_name = None

    try:
        task_queue_name = os.environ['SQS_TASK_QUEUE']
        task_completed_queue_name = os.environ['SQS_TASK_COMPLETED_QUEUE']
    except KeyError:
        print('Please set the environment variables for SQS_TASK_QUEUE and SQS_TASK_COMPLETED_QUEUE')
        sys.exit(1)

    print(task_queue_name)
    print(task_completed_queue_name)

    # Get the instance information
    r = requests.get("http://169.254.169.254/latest/dynamic/instance-identity/document")
    r.raise_for_status()
    response_json = r.json()
    region = response_json.get('region')
    instance_id = response_json.get('instanceId')
    ec2_client = boto3.client('ec2', region_name=region)

    task_queue = boto3.resource('sqs', region_name=region).get_queue_by_name(QueueName=task_queue_name)
    task_completed_queue = boto3.resource('sqs', region_name=region).get_queue_by_name(QueueName=task_completed_queue_name)

    while True:
        for message in task_queue.receive_messages(WaitTimeSeconds=20):
            try:
                print('message received')
                ec2_client.client.modify_instance_attribute(
                    InstanceId=instance_id,
                    DisableApiTermination={ 'Value': True },
                )
                message.change_visibility(VisibilityTimeout=600)

                # Process the message

                task_completed_queue.send_message(MessageBody='completed')
                message.delete()

                ec2_client.client.modify_instance_attribute(
                    InstanceId=instance-id,
                    DisableApiTermination={ 'Value': False },
                )
            except:
                print('Problem processing message')

if __name__ == '__main__':
    main()
