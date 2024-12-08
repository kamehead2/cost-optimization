import os
import json
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone, timedelta
from ibm_vpc import VpcV1
from ibm_platform_services import UsageReportsV4
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
import requests

# 環境変数
APIKEY = os.getenv("APIKEY")
ACCOUNT_ID = os.getenv("ACCOUNT_ID")
TEAMS_WORKFLOW_URL = os.getenv("TEAMS_WORKFLOW_URL")
REGION = "jp-tok"

# 認証設定
authenticator = IAMAuthenticator(APIKEY)
vpc_service = VpcV1(authenticator=authenticator)
vpc_service.set_service_url(f"https://{REGION}.iaas.cloud.ibm.com/v1")

usage_reports_service = UsageReportsV4(authenticator=authenticator)
usage_reports_service.set_service_url("https://billing.cloud.ibm.com")


# 1. 'unattached' のボリュームをリスト
def list_unattached_volumes():
    unattached_volumes = []
    next_url = None

    while True:
        if next_url:
            parsed_url = urlparse(next_url)
            query_params = parse_qs(parsed_url.query)
            response = vpc_service.list_volumes(start=query_params.get('start', [None])[0]).get_result()
        else:
            response = vpc_service.list_volumes().get_result()

        volumes = response.get("volumes", [])
        for volume in volumes:
            if volume.get("attachment_state") == "unattached":
                unattached_volumes.append(volume)

        next_url = response.get("next", {}).get("href")
        if not next_url:
            break

    return unattached_volumes


# 2. CRN から前月のコストを取得
def get_previous_month_cost(resource_crn):
    now = datetime.now(timezone.utc)
    first_day_of_current_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    last_day_of_previous_month = first_day_of_current_month - timedelta(days=1)
    year_month = last_day_of_previous_month.strftime("%Y-%m")

    response = usage_reports_service.get_resource_usage_account(
        account_id=ACCOUNT_ID,
        billingmonth=year_month,
        resource_instance_id=resource_crn
    ).get_result()

    device_cost = 0.0
    resources = response.get("resources", [])
    for resource in resources:
        for usage in resource.get("usage", []):
            device_cost += usage.get("cost", 0.0)

    return device_cost


# 3. 各ボリュームのコストを取得
def fetch_volumes_with_cost(volumes):
    enriched_volumes = []
    for volume in volumes:
        volume_id = volume.get("id")
        crn = volume.get("crn")
        try:
            # コストを取得
            cost = get_previous_month_cost(crn)
            volume["cost"] = cost  # コストをボリューム情報に追加
        except Exception as e:
            volume["cost"] = 0.0  # エラー時は 0 に設定
            print(f"コスト取得中にエラー: {volume_id}, {e}")
        enriched_volumes.append(volume)
    return enriched_volumes


# 4. Adaptive Card の作成
def create_adaptive_card_body(volumes):
    # 合計コストを計算
    total_cost = sum(volume.get("cost", 0.0) for volume in volumes)

    # Adaptive Card の本文
    card_body = [
        {
            "type": "TextBlock",
            "text": "未使用ブロックストレージとそのコスト",
            "weight": "Bolder",
            "size": "ExtraLarge",
            "wrap": True
        },
        {
            "type": "TextBlock",
            "text": f"**合計コスト**: ¥{total_cost:.2f}",
            "weight": "Bolder",
            "size": "Large",
            "wrap": True
        }
    ]

    # 各ボリュームの詳細を追加
    for volume in volumes:
        description = (
            f"ID: {volume['id']}, 名前: {volume['name']}, "
            f"サイズ: {volume['capacity']}GB, 前月のコスト: ¥{volume.get('cost', 0.0):.2f}"
        )
        card_body.append({
            "type": "TextBlock",
            "text": description,
            "wrap": True
        })

    return card_body


# 5. Teams に Adaptive Card を送信 (Workflow 経由)
def send_to_teams(card_body):
    headers = {"Content-Type": "application/json"}
    adaptive_card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "msteams": {"width": "Full"},
        "version": "1.5",
        "body": card_body
    }
    message = {
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": adaptive_card
            }
        ]
    }

    try:
        response = requests.post(TEAMS_WORKFLOW_URL, headers=headers, data=json.dumps(message))
        response.raise_for_status()
        print(f"Adaptive Card の送信が成功しました: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Adaptive Card の送信中にエラーが発生しました: {e}")


# 6. 結果を取得し Teams に送信
def main():
    unattached_volumes = list_unattached_volumes()

    if not unattached_volumes:
        print("Attachment state が 'unattached' のボリュームは見つかりませんでした。")
        send_to_teams(create_adaptive_card_body([]))
        return

    # コストを取得し、ボリューム情報を更新
    volumes_with_cost = fetch_volumes_with_cost(unattached_volumes)

    # Adaptive Card の本文を作成して Teams に送信
    card_body = create_adaptive_card_body(volumes_with_cost)
    send_to_teams(card_body)


if __name__ == "__main__":
    main()
