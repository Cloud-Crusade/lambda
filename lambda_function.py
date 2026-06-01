import json
import uuid
import boto3
import os

# SQS 연결
sqs = boto3.client('sqs')

# 환경변수에서 SQS URL 가져오기 (보안상 코드에 직접 쓰지 않음)
QUEUE_URL = os.environ.get('SQS_URL', '')

def lambda_handler(event, context):
    
    # UUID 번호표 발급
    ticket_uuid = str(uuid.uuid4())
    
    # SQS 대기열에 번호표 넣기
    sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps({
            'uuid': ticket_uuid,
            'message': '대기열에 등록되었습니다'
        }),
        MessageGroupId='ticket-group',      # FIFO 필수 설정
        MessageDeduplicationId=ticket_uuid  # 중복 방지
    )
    
    # 결과 반환
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': '번호표가 발급되고 대기열에 등록되었습니다',
            'uuid': ticket_uuid
        }, ensure_ascii=False)
    }