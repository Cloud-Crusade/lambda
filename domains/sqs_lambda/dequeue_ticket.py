import json
import boto3
import os

def lambda_handler(event, context):
    
    # SQS에서 꺼낸 메시지 처리
    for record in event['Records']:
        
        # 메시지 내용 읽기
        body = json.loads(record['body'])
        ticket_uuid = body['uuid']
        
        print(f"처리 중인 티켓 UUID: {ticket_uuid}")
        
        # 여기서 EKS로 전달하는 로직 추가 예정
        # 현재는 수신 확인만 함
        
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': '대기열 처리 완료',
        }, ensure_ascii=False)
    }