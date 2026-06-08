from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
import smtplib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decrypt_secret, utcnow
from app.models.notification import NotificationRecipient, NotificationSetting
from app.models.platform import RelayPlatform


@dataclass(frozen=True)
class GroupRateChange:
    group_name: str
    external_group_id: str
    old_rate: float
    new_rate: float
    rpm_limit: int | None


@dataclass(frozen=True)
class GroupCatalogChange:
    action: str
    group_name: str
    external_group_id: str
    rate_multiplier: float | None
    rpm_limit: int | None


LOW_BALANCE_MAX_CONSECUTIVE_NOTIFICATIONS = 3


def get_notification_setting(db: Session) -> NotificationSetting:
    setting = db.get(NotificationSetting, 1)
    if setting is not None:
        return setting
    setting = NotificationSetting(id=1)
    db.add(setting)
    db.flush()
    return setting


def notification_ready(setting: NotificationSetting) -> bool:
    return not notification_config_errors(setting)


def notification_config_errors(setting: NotificationSetting) -> list[str]:
    errors: list[str] = []
    if not setting.enabled:
        errors.append("未启用邮件通知")
    if not setting.smtp_host or not setting.smtp_host.strip():
        errors.append("未配置 SMTP 主机")
    if not setting.smtp_port:
        errors.append("未配置 SMTP 端口")
    if not setting.from_email or not setting.from_email.strip():
        errors.append("未配置发件人邮箱")
    if setting.smtp_use_ssl and setting.smtp_use_tls:
        errors.append("SSL 和 STARTTLS 不能同时启用")
    return errors


def send_mail(
    setting: NotificationSetting,
    recipients: list[NotificationRecipient],
    subject: str,
    body: str,
) -> None:
    config_errors = notification_config_errors(setting)
    if config_errors:
        raise ValueError("邮件通知配置不完整：" + "；".join(config_errors))
    recipient_emails = [recipient.email for recipient in recipients if recipient.enabled]
    if not recipient_emails:
        raise ValueError("邮件通知配置不完整：没有启用的邮件收件人")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((setting.from_name or "", setting.from_email or ""))
    message["To"] = ", ".join(recipient_emails)
    message.set_content(body)

    password = decrypt_secret(setting.smtp_password_encrypted)
    smtp_class = smtplib.SMTP_SSL if setting.smtp_use_ssl else smtplib.SMTP
    with smtp_class(setting.smtp_host or "", setting.smtp_port, timeout=15) as smtp:
        if setting.smtp_use_tls and not setting.smtp_use_ssl:
            smtp.starttls()
        if setting.smtp_username:
            smtp.login(setting.smtp_username, password or "")
        smtp.send_message(message)


def enabled_recipients(db: Session) -> list[NotificationRecipient]:
    return list(
        db.scalars(
            select(NotificationRecipient)
            .where(NotificationRecipient.enabled.is_(True))
            .order_by(NotificationRecipient.created_at.asc())
        ).all()
    )


def send_test_email(db: Session, recipient: NotificationRecipient) -> None:
    setting = get_notification_setting(db)
    try:
        send_mail(
            setting,
            [recipient],
            "Sub2 Monitor 测试邮件",
            "这是一封 Sub2 Monitor 邮件通知测试。收到此邮件说明 SMTP 配置可用。",
        )
        setting.last_error = None
        recipient.last_error = None
    except Exception as exc:  # noqa: BLE001
        setting.last_error = str(exc)
        recipient.last_error = str(exc)
        raise
    finally:
        tested_at = utcnow()
        setting.last_tested_at = tested_at
        recipient.last_tested_at = tested_at
        db.add(setting)
        db.add(recipient)
        db.commit()


def notify_group_rate_changes(
    db: Session,
    platform: RelayPlatform,
    changes: list[GroupRateChange],
    catalog_changes: list[GroupCatalogChange] | None = None,
) -> None:
    catalog_changes = catalog_changes or []
    if not changes and not catalog_changes:
        return
    setting = get_notification_setting(db)
    if not setting.notify_group_rate_changes:
        return
    config_errors = notification_config_errors(setting)
    if config_errors:
        setting.last_error = "邮件通知配置不完整：" + "；".join(config_errors)
        db.add(setting)
        return
    recipients = enabled_recipients(db)
    if not recipients:
        setting.last_error = "邮件通知配置不完整：没有启用的邮件收件人"
        db.add(setting)
        return

    lines = [
        f"平台：{platform.name}",
        f"地址：{platform.base_url}",
        "",
        "检测到分组变化：",
    ]
    if changes:
        lines.append("")
        lines.append("倍率变化：")
        for change in changes:
            rpm = change.rpm_limit if change.rpm_limit is not None else "-"
            lines.append(
                f"- {change.group_name} ({change.external_group_id}): "
                f"{format_rate(change.old_rate)} -> {format_rate(change.new_rate)}，RPM: {rpm}"
            )
    if catalog_changes:
        lines.append("")
        lines.append("分组新增/减少：")
        for change in catalog_changes:
            action_label = "新增" if change.action == "added" else "减少"
            rate = format_optional_rate(change.rate_multiplier)
            rpm = change.rpm_limit if change.rpm_limit is not None else "-"
            lines.append(
                f"- {action_label} {change.group_name} ({change.external_group_id})，"
                f"倍率: {rate}，RPM: {rpm}"
            )

    try:
        send_mail(
            setting,
            recipients,
            f"Sub2 Monitor 分组变化 - {platform.name}",
            "\n".join(lines),
        )
        setting.last_error = None
        for recipient in recipients:
            recipient.last_error = None
    except Exception as exc:  # noqa: BLE001
        setting.last_error = str(exc)
        for recipient in recipients:
            recipient.last_error = str(exc)
    finally:
        db.add(setting)
        for recipient in recipients:
            db.add(recipient)


def notify_low_balance(
    db: Session,
    platform: RelayPlatform,
) -> None:
    if platform.balance is None or platform.low_balance_threshold is None:
        return

    if platform.balance >= platform.low_balance_threshold:
        if platform.low_balance_notify_count:
            platform.low_balance_notify_count = 0
            db.add(platform)
        return

    if platform.low_balance_notify_count >= LOW_BALANCE_MAX_CONSECUTIVE_NOTIFICATIONS:
        return

    setting = get_notification_setting(db)
    if not setting.notify_low_balance:
        return

    config_errors = notification_config_errors(setting)
    if config_errors:
        setting.last_error = "邮件通知配置不完整：" + "；".join(config_errors)
        db.add(setting)
        return

    recipients = enabled_recipients(db)
    if not recipients:
        setting.last_error = "邮件通知配置不完整：没有启用的邮件收件人"
        db.add(setting)
        return

    body = "\n".join(
        [
            f"平台：{platform.name}",
            f"地址：{platform.base_url}",
            f"当前余额：{format_rate(platform.balance)}",
            f"提醒阈值：{format_rate(platform.low_balance_threshold)}",
            f"连续提醒次数：{platform.low_balance_notify_count + 1}/{LOW_BALANCE_MAX_CONSECUTIVE_NOTIFICATIONS}",
        ]
    )

    try:
        send_mail(
            setting,
            recipients,
            f"Sub2 Monitor 额度不足提醒 - {platform.name}",
            body,
        )
        setting.last_error = None
        platform.low_balance_notify_count += 1
        for recipient in recipients:
            recipient.last_error = None
    except Exception as exc:  # noqa: BLE001
        setting.last_error = str(exc)
        for recipient in recipients:
            recipient.last_error = str(exc)
    finally:
        db.add(setting)
        db.add(platform)
        for recipient in recipients:
            db.add(recipient)


def format_rate(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def format_optional_rate(value: float | None) -> str:
    return format_rate(value) if value is not None else "-"
