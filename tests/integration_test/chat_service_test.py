import asyncio
import json
import os

from mock import patch
from mongoengine import connect
from tornado.test.testing_test import AsyncHTTPTestCase

from kairon.api.models import RegisterAccount
from kairon.chat.server import make_app
from kairon.shared.account.processor import AccountProcessor
from kairon.shared.auth import Authentication
from kairon.shared.chat.processor import ChatDataProcessor
from kairon.shared.data.constant import TOKEN_TYPE
from kairon.shared.data.processor import MongoProcessor
from kairon.shared.utils import Utility
from kairon.train import start_training
import responses


os.environ["system_file"] = "./tests/testing_data/system.yaml"
os.environ['ASYNC_TEST_TIMEOUT'] = "3600"
Utility.load_environment()
connect(**Utility.mongoengine_connection())

loop = asyncio.new_event_loop()
loop.run_until_complete(AccountProcessor.account_setup(RegisterAccount(**{"email": "test@chat.com",
                                                                          "first_name": "Test",
                                                                          "last_name": "Chat",
                                                                          "password": "testChat@12",
                                                                          "confirm_password": "testChat@12",
                                                                          "account": "ChatTesting"}).dict(),
                                                       "sysadmin"))

token = Authentication.authenticate("test@chat.com", "testChat@12")
token_type = "Bearer"
user = AccountProcessor.get_complete_user_details("test@chat.com")
bot = user['bots']['account_owned'][0]['_id']
start_training(bot, "test@chat.com")
bot2 = AccountProcessor.add_bot("testChat2", user['account'], "test@chat.com")['_id'].__str__()
loop.run_until_complete(MongoProcessor().save_from_path(
    "template/use-cases/Hi-Hello", bot2, user="test@chat.com"
))
start_training(bot2, "test@chat.com")
bot3 = AccountProcessor.add_bot("testChat3", user['account'], "test@chat.com")['_id'].__str__()
ChatDataProcessor.save_channel_config({"connector_type": "slack",
                                       "config": {
                                           "slack_token": "xoxb-801939352912-801478018484-v3zq6MYNu62oSs8vammWOY8K",
                                           "slack_signing_secret": "79f036b9894eef17c064213b90d1042b"}},
                                      bot, user=user)
responses.start()
responses.add("GET",
              json={"result": True},
              url="https://api.telegram.org/botxoxb-801939352912-801478018484/setWebhook?url=https://test@test.com/api/bot/telegram/tests/test")
ChatDataProcessor.save_channel_config({"connector_type": "telegram",
                                       "config": {
                                           "access_token": "xoxb-801939352912-801478018484",
                                           "webhook_url": "https://test@test.com/api/bot/telegram/tests/test",
                                           "bot_name": "test"}},
                                      bot, user=user)
responses.stop()

class TestChatServer(AsyncHTTPTestCase):

    def get_app(self):
        return make_app()

    def empty_store(self, *args, **kwargs):
        return None

    def test_index(self):
        response = self.fetch("/")
        self.assertEqual(response.code, 200)
        self.assertEqual(response.body.decode("utf8"), 'Kairon Server Running')

    def test_chat(self):
        with patch.object(Utility, "get_local_mongo_store") as mocked:
            mocked.side_effect = self.empty_store
            patch.dict(Utility.environment['action'], {"url": None})
            response = self.fetch(
                f"/api/bot/{bot}/chat",
                method="POST",
                body=json.dumps({"data": "Hi"}).encode('utf-8'),
                headers={"Authorization": token_type + " " + token},
                connect_timeout=0,
                request_timeout=0
            )
            actual = json.loads(response.body.decode("utf8"))
            self.assertEqual(response.code, 200)
            assert actual["success"]
            assert actual["error_code"] == 0
            assert actual["data"]
            assert Utility.check_empty_string(actual["message"])

    def test_chat_with_user(self):
        with patch.object(Utility, "get_local_mongo_store") as mocked:
            mocked.side_effect = self.empty_store
            patch.dict(Utility.environment['action'], {"url": None})

            response = self.fetch(
                f"/api/bot/{bot}/chat",
                method="POST",
                body=json.dumps({"data": "Hi"}).encode("utf8"),
                headers={"Authorization": token_type + " " + token},
            )
            actual = json.loads(response.body.decode("utf8"))
            self.assertEqual(response.code, 200)
            assert actual["success"]
            assert actual["error_code"] == 0
            assert actual["data"]
            assert Utility.check_empty_string(actual["message"])

    def test_chat_fetch_from_cache(self):
        with patch.object(Utility, "get_local_mongo_store") as mocked:
            mocked.side_effect = self.empty_store
            patch.dict(Utility.environment['action'], {"url": None})

            response = self.fetch(
                f"/api/bot/{bot}/chat",
                method="POST",
                body=json.dumps({"data": "Hi"}).encode("utf8"),
                headers={"Authorization": token_type + " " + token},
            )
            actual = json.loads(response.body.decode("utf8"))
            self.assertEqual(response.code, 200)
            assert actual["success"]
            assert actual["error_code"] == 0
            assert actual["data"]
            assert Utility.check_empty_string(actual["message"])

    def test_chat_model_not_trained(self):
        response = self.fetch(
            f"/api/bot/{bot3}/chat",
            method="POST",
            body=json.dumps({"data": "Hi"}).encode("utf8"),
            headers={
                "Authorization": f"{token_type} {token}"
            },
        )
        actual = json.loads(response.body.decode("utf8"))
        self.assertEqual(response.code, 200)
        assert not actual["success"]
        assert actual["error_code"] == 422
        assert actual["data"] is None
        assert actual["message"] == "Bot has not been trained yet!"

    def test_chat_with_different_bot_not_allowed(self):
        response = self.fetch(
            f"/api/bot/test/chat",
            method="POST",
            body=json.dumps({"data": "Hi"}).encode("utf8"),
            headers={
                "Authorization": token_type + " " + token
            },
        )
        actual = json.loads(response.body.decode("utf8"))
        self.assertEqual(response.code, 200)
        assert not actual["success"]
        assert actual["error_code"] == 422
        assert actual["data"] is None
        assert actual["message"] == "Access to bot is denied"

    def test_chat_different_bot(self):
        with patch.object(Utility, "get_local_mongo_store") as mocked:
            mocked.side_effect = self.empty_store
            patch.dict(Utility.environment['action'], {"url": None})
            response = self.fetch(
                f"/api/bot/{bot2}/chat",
                method="POST",
                body=json.dumps({"data": "Hi"}).encode("utf8"),
                headers={"Authorization": token_type + " " + token},
                connect_timeout=0,
                request_timeout=0
            )
            actual = json.loads(response.body.decode("utf8"))
            self.assertEqual(response.code, 200)
            assert actual["success"]
            assert actual["error_code"] == 0
            assert actual["data"]
            assert Utility.check_empty_string(actual["message"])

    def test_chat_with_limited_access(self):
        access_token = Authentication.create_access_token(
            data={"sub": "test@chat.com", 'access-limit': ['/api/bot/.+/chat']},
            token_type=TOKEN_TYPE.INTEGRATION.value
        )
        response = self.fetch(
            f"/api/bot/{bot2}/chat",
            method="POST",
            body=json.dumps({"data": "Hi"}).encode("utf8"),
            headers={
                "Authorization": f"{token_type} {access_token}", 'X-USER': 'testUser'
            },
        )
        actual = json.loads(response.body.decode("utf8"))
        self.assertEqual(response.code, 200)
        assert actual['data']['response']

    def test_chat_with_limited_access_without_integration(self):
        access_token = Authentication.create_access_token(
            data={"sub": "test@chat.com", 'access-limit': ['/api/bot/.+/chat']},
        )
        response = self.fetch(
            f"/api/bot/{bot2}/chat",
            method="POST",
            body=json.dumps({"data": "Hi"}).encode("utf8"),
            headers={
                "Authorization": f"{token_type} {access_token}", 'X-USER': 'testUser'
            },
        )
        actual = json.loads(response.body.decode("utf8"))
        self.assertEqual(response.code, 200)
        assert actual['data']['response']

    def test_chat_limited_access_prevent_chat(self):
        access_token = Authentication.create_access_token(
            data={"sub": "test@chat.com", 'access-limit': ['/api/bot/.+/intent']},
            token_type=TOKEN_TYPE.INTEGRATION.value
        )
        response = self.fetch(
            f"/api/bot/{bot}/chat",
            method="POST",
            body=json.dumps({"data": "Hi"}).encode("utf8"),
            headers={
                "Authorization": f"{token_type} {access_token}", 'X-USER': "testUser"
            },
        )
        actual = json.loads(response.body.decode("utf8"))
        assert actual["message"] == "Access denied for this endpoint"

    def test_reload(self):
        response = self.fetch(
            f"/api/bot/{bot}/reload",
            method="GET",
            headers={
                "Authorization": token_type + " " + token
            },
        )
        actual = json.loads(response.body.decode("utf8"))
        self.assertEqual(response.code, 200)
        assert actual["success"]
        assert actual["error_code"] == 0
        assert actual["data"] is None
        assert actual["message"] == "Reloading Model!"

    @patch('kairon.chat.handlers.channels.slack.SlackHandler.is_request_from_slack_authentic')
    @patch('kairon.shared.utils.Utility.get_local_mongo_store')
    def test_slack_auth_bot_challenge(self, mock_store, mock_slack):
        mock_store.return_value = self.empty_store
        mock_slack.return_value = True
        headers = {'User-Agent': 'Slackbot 1.0 (+https://api.slack.com/robots)',
                   'Content-Length': 826,
                   'Accept': '*/*',
                   'Accept-Encoding': 'gzip,deflate',
                   'Cache-Control': 'max-age=259200',
                   'Content-Type': 'application/json',
                   'X-Forwarded-For': '3.237.67.113',
                   'X-Forwarded-Proto': 'http',
                   'X-Slack-Request-Timestamp': '1644676934',
                   'X-Slack-Retry-Reason': 'http_error',
                   'X-Slack-Signature': 'v0=65e62a2a81ebac3825a7aeec1f7033977e31f6ccff988ec11aaf06884553834a'}
        patch.dict(Utility.environment['action'], {"url": None})
        response = self.fetch(
            f"/api/bot/slack/{bot}/{token}",
            method="POST",
            headers=headers,
            body=json.dumps({"token": "RrNd3SaNJNaP28TTauAYCmJw",
                             "challenge": "sjYDB2ccaT5wpcGyawz6BTDbiujZCBiVwSQR87t3Q3yqgoHFkkTy",
                             "type": "url_verification"},
                            )
        )
        actual = response.body.decode("utf8")
        self.assertEqual(response.code, 200)
        assert actual == "sjYDB2ccaT5wpcGyawz6BTDbiujZCBiVwSQR87t3Q3yqgoHFkkTy"

    def test_slack_invalid_auth(self):
        headers = {'User-Agent': 'Slackbot 1.0 (+https://api.slack.com/robots)',
                   'Content-Length': 826,
                   'Accept': '*/*',
                   'Accept-Encoding': 'gzip,deflate',
                   'Cache-Control': 'max-age=259200',
                   'Content-Type': 'application/json',
                   'X-Forwarded-For': '3.237.67.113',
                   'X-Forwarded-Proto': 'http',
                   'X-Slack-Request-Timestamp': '1644676934',
                   'X-Slack-Retry-Num': '1',
                   'X-Slack-Retry-Reason': 'http_error',
                   'X-Slack-Signature': 'v0=65e62a2a81ebac3825a7aeec1f7033977e31f6ccff988ec11aaf06884553834a'}
        patch.dict(Utility.environment['action'], {"url": None})
        response = self.fetch(
            f"/api/bot/slack/{bot}/123",
            method="POST",
            headers=headers,
            body=json.dumps({"token":"RrNd3SaNJNaP28TTauAYCmJw","team_id":"TPKTMACSU","api_app_id":"APKTXRPMK","event":{"client_msg_id":"77eafc15-4e7a-46d1-b03f-bf953fa801dc","type":"message","text":"Hi","user":"UPKTMK5BJ","ts":"1644670603.521219","team":"TPKTMACSU","blocks":[{"type":"rich_text","block_id":"ssu6","elements":[{"type":"rich_text_section","elements":[{"type":"text","text":"Hi"}]}]}],"channel":"DPKTY81UM","event_ts":"1644670603.521219","channel_type":"im"},"type":"event_callback","event_id":"Ev032U6W5N1G","event_time":1644670603,"authed_users":["UPKE20JE8"],"authorizations":[{"enterprise_id":None,"team_id":"TPKTMACSU","user_id":"UPKE20JE8","is_bot":True,"is_enterprise_install":False}],"is_ext_shared_channel":False,"event_context":"4-eyJldCI6Im1lc3NhZ2UiLCJ0aWQiOiJUUEtUTUFDU1UiLCJhaWQiOiJBUEtUWFJQTUsiLCJjaWQiOiJEUEtUWTgxVU0ifQ"})
        )
        actual = response.body.decode("utf8")
        self.assertEqual(response.code, 500)
        assert actual == "<html><title>500: Internal Server Error</title><body>500: Internal Server Error</body></html>"

    @patch('kairon.chat.handlers.channels.telegram.TelegramOutput')
    @patch('kairon.shared.utils.Utility.get_local_mongo_store')
    def test_telegram_auth_failed_telegram_verify(self, mock_store, mock_telegram_out):
        mock_store.return_value = self.empty_store
        mock_telegram_out.get_me.return_value = "test"
        patch.dict(Utility.environment['action'], {"url": None})
        response = self.fetch(
            f"/api/bot/telegram/{bot}/{token}",
            method="POST",
            body=json.dumps({"update_id":483117514, "message": {"message_id":14,"from":{"id":1422280657,"is_bot":False,"first_name":"Fahad Ali","language_code":"en"},"chat":{"id":1422280657,"first_name":"Fahad Ali","type":"private"},"date":1645433258,"text":"hi"}})
        )
        actual = response.body.decode("utf8")
        self.assertEqual(response.code, 200)
        assert actual == "failed"

    def test_telegram_invalid_auth(self):
        patch.dict(Utility.environment['action'], {"url": None})
        response = self.fetch(
            f"/api/bot/telegram/{bot}/123",
            method="POST",
            body=json.dumps({"update_id":483117514, "message": {"message_id":14,"from":{"id":1422280657,"is_bot":False,"first_name":"Fahad Ali","language_code":"en"},"chat":{"id":1422280657,"first_name":"Fahad Ali","type":"private"},"date":1645433258,"text":"hi"}})
        )
        actual = response.body.decode("utf8")
        self.assertEqual(response.code, 500)
        assert actual == "<html><title>500: Internal Server Error</title><body>500: Internal Server Error</body></html>"
