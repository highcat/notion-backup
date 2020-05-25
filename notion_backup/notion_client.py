import requests

from notion_backup.configuration_service import ConfigurationService

NOTION_API_ROOT = "https://www.notion.so/api/v3"


class NotionClient:
    def __init__(self, configuration_service: ConfigurationService):
        self.configuration_service = configuration_service

    def ask_otp(self):
        response = requests.request(
            "POST",
            f"{NOTION_API_ROOT}/sendTemporaryPassword",
            json={
                "email": self.configuration_service.get_key("email"),
                "disableLoginLink": False,
                "native": False,
                "isSignup": False,
            },
        )
        response.raise_for_status()
        json_response = response.json()
        return {"csrf_state": json_response["csrfState"], "csrf_cookie": response.cookies["csrf"]}

    def get_token(self, csrf_values, otp):
        response = requests.request(
            "POST",
            f"{NOTION_API_ROOT}/loginWithEmail",
            json={"state": csrf_values["csrf_state"], "password": otp},
            cookies={'csrf': csrf_values["csrf_cookie"]},
        )
        response.raise_for_status()
        return response.cookies["token_v2"]