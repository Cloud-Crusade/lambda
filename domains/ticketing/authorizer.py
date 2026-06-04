import os
import logging

import jwt

logger = logging.getLogger()
logger.setLevel(logging.INFO)

JWT_SECRET = os.environ.get('JWT_SECRET', 'secret')
JWT_ALGORITHM = os.environ.get('JWT_ALGORITHM', 'HS256')


def _extract_token(event):
    # TOKEN authorizer
    token = event.get('authorizationToken', '')
    if not token:
        # REQUEST authorizer
        headers = event.get('headers') or {}
        token = headers.get('Authorization') or headers.get('authorization') or ''
    return token.replace('Bearer', '').strip()


def _policy(principal_id, effect, resource, context=None):
    document = {
        'principalId': principal_id,
        'policyDocument': {
            'Version': '2012-10-17',
            'Statement': [{
                'Action': 'execute-api:Invoke',
                'Effect': effect,
                'Resource': resource
            }]
        }
    }
    if context:
        document['context'] = context
    return document


def lambda_handler(event, context):
    method_arn = event.get('methodArn', '*')
    token = _extract_token(event)

    if not token:
        logger.debug("토큰 없음")
        return _policy('anonymous', 'Deny', method_arn)

    # Authorization 토큰을 해체해 user_id 확인 (서명·만료 검증)
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as error:
        logger.debug(f"토큰 검증 실패: {error}")
        return _policy('anonymous', 'Deny', method_arn)

    user_id = payload.get('user_id', '')
    if not user_id:
        logger.debug("토큰에 user_id 없음")
        return _policy('anonymous', 'Deny', method_arn)

    # 검증 통과 시 Allow 반환, user_id는 context로 백엔드에 전달
    logger.debug(f"인증 성공: user_id={user_id}")
    return _policy(user_id, 'Allow', method_arn, context={'user_id': user_id})
