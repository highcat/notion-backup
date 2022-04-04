from datetime import datetime
from operator import itemgetter
from pathlib import Path
from time import sleep

import click
import requests
import shutil
from prompt_toolkit import prompt
from tqdm import tqdm

from notion_backup.configuration_service import ConfigurationService
from notion_backup.notion_client import NotionClient

STATUS_WAIT_TIME = 5
block_size = 1024  # 1 Kibibyte


class BackupService:
    def __init__(self, output_dir_path, space_id, export_type, noinput, copy_dir):
        self.output_dir_path = output_dir_path
        self.space_id = space_id
        self.export_type = export_type
        self.noinput = noinput
        self.copy_dir = copy_dir
        if not self.output_dir_path.exists():
            raise Exception(f'Output directory {self.output_dir_path.resolve()} does not exit')
        if export_type not in ("html", "markdown"):
            raise Exception('Export type should be either "html" or "markdown"')
        if copy_dir and not Path(copy_dir).is_dir():
            raise Exception('copy-dir: directory does not exist')
        self.configuration_service = ConfigurationService()
        self.notion_client = NotionClient(self.configuration_service)

    def _login(self):
        email = self.configuration_service.get_key("email")
        if email:
            email = prompt("Email address: ", default=email)
        else:
            email = prompt("Email address: ")
        self.configuration_service.write_key("email", email)

        csrf_values = self.notion_client.ask_otp()
        print(f"A one temporary password has been sent to your email address {email}")
        otp = prompt("Temporary password: ")

        token = self.notion_client.get_token(csrf_values, otp)
        self.configuration_service.write_key("token", token)
        print("Congratulations, you have been successfully authenticated")

    def _download_file(self, url, export_file: Path):
        with requests.get(url, stream=True, allow_redirects=True) as response:
            total_size = int(response.headers.get("content-length", 0))
            tqdm_bar = tqdm(total=total_size, unit="iB", unit_scale=True)
            with export_file.open("wb") as export_file_handle:
                for data in response.iter_content(block_size):
                    tqdm_bar.update(len(data))
                    export_file_handle.write(data)
            tqdm_bar.close()

    def _copy_file(self, export_source: Path, destination_dir: Path):
        shutil.copy(export_source, destination_dir / export_source.name)

    def backup(self):
        token = self.configuration_service.get_key("token")
        if not token:
            print("First time login")
            if self.noinput:
                raise Exception("Please run the script manually to obtain an API token.")
            self._login()

        try:
            self.notion_client.get_user_content()
        except requests.exceptions.HTTPError as err:
            if err.response.status_code == 401:
                if self.noinput:
                    raise Exception("Credentials expired. Please run the script manually to obtain an API token.")
                print("Credentials have expired, login again")
                self._login()

        user_content = self.notion_client.get_user_content()

        user_id = list(user_content["notion_user"].keys())[0]
        print(f"User id: {user_id}")

        spaces = [
            (space_id, space_details["value"]["name"])
            for (space_id, space_details) in user_content["space"].items()
        ]
        print("Available spaces:")
        for (space_id, space_name) in spaces:
            print(f"\t- {space_name}: {space_id}")

        if self.space_id:
            print(f"Selecting space {self.space_id}")
            space_id=self.space_id
        else:
            if self.noinput:
                raise Exception("Please specify space-id")
            space_id = self.configuration_service.get_key("space_id")
            space_id = prompt("Select space id: ", default=(space_id or spaces[0][0]))

        if space_id not in map(itemgetter(0), spaces):
            raise Exception("Selected space id not in list")

        self.configuration_service.write_key("space_id", space_id)

        print("Launching export task")
        task_id = self.notion_client.launch_export_task(space_id, self.export_type)
        print(f"Export task {task_id} has been launched")

        while True:
            task_status = self.notion_client.get_user_task_status(task_id)
            if task_status["status"]["type"] == "complete":
                break
            print(
                f"...Export still in progress, waiting for {STATUS_WAIT_TIME} seconds"
            )
            sleep(STATUS_WAIT_TIME)
        print("Export task is finished")

        export_link = task_status["status"]["exportURL"]
        export_format = task_status["request"]["exportOptions"]["exportType"]
        print(f"Downloading zip export from {export_link}")

        postfix_number = 0
        while True:
            postfix = f"_{postfix_number}" if postfix_number else ""
            export_file_name = f'export_{space_id}_{datetime.now().strftime("%Y-%m-%d")}_{export_format}{postfix}.zip'
            export_path = self.output_dir_path / export_file_name
            if not Path(export_path).exists():
                break
            postfix_number += 1

        self._download_file(export_link, export_path)

        if self.copy_dir:
            self._copy_file(export_path, Path(self.copy_dir))


@click.command()
@click.option("--output-dir", default=".", help="Where the zip export will be saved")
@click.option("--space-id", help="Id of Notion workspace")
@click.option("--export-type", default="markdown", help="html or markdown")
@click.option("--noinput", is_flag=True, show_default=True, default=False, help="return error on missing token or space-id")
@click.option("--copy-dir", default=None, help="Optinally save a copy of export to this dir")
def main(output_dir, space_id, export_type, noinput, copy_dir):
    output_dir_path = Path(output_dir)
    print(f"Backup Notion workspace into directory {output_dir_path.resolve()}")
    backup_service = BackupService(output_dir_path, space_id, export_type, noinput, copy_dir)
    backup_service.backup()


if __name__ == '__main__':
    main()
