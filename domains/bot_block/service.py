import json


class BotBlockService:
    def process(self, event: dict) -> dict:
        print("Received EventBridge event")
        print(json.dumps(event, ensure_ascii=False))

        return {
            "statusCode": 200,
            "body": "Bot event processed"
        }