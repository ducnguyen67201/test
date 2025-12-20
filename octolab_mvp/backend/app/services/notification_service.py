"""Notification service for Slack and Discord webhook alerts.

Supports:
- Slack webhooks for instant alerts
- Discord webhooks for instant alerts

Configuration via environment variables:
- OCTOLAB_SLACK_WEBHOOK_URL: Slack incoming webhook URL
- OCTOLAB_DISCORD_WEBHOOK_URL: Discord webhook URL
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class AlertPayload:
    """Payload for alert notifications."""

    title: str
    message: str
    severity: str = "warning"  # info, warning, error, critical
    details: list[dict[str, Any]] | None = None
    timestamp: datetime | None = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


async def send_slack_alert(payload: AlertPayload) -> bool:
    """Send alert to Slack via webhook.

    Args:
        payload: Alert payload with title, message, severity, and optional details

    Returns:
        True if sent successfully, False otherwise
    """
    webhook_url = settings.slack_webhook_url
    if not webhook_url:
        logger.debug("Slack webhook not configured, skipping")
        return False

    # Map severity to emoji and color
    severity_config = {
        "info": {"emoji": ":information_source:", "color": "#2196F3"},
        "warning": {"emoji": ":warning:", "color": "#FFC107"},
        "error": {"emoji": ":x:", "color": "#F44336"},
        "critical": {"emoji": ":rotating_light:", "color": "#9C27B0"},
    }
    config = severity_config.get(payload.severity, severity_config["warning"])

    # Build Slack message blocks
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{config['emoji']} {payload.title}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": payload.message,
            },
        },
    ]

    # Add details as fields if provided
    if payload.details:
        fields = []
        for detail in payload.details[:10]:  # Limit to 10 items
            cve_id = detail.get("cve_id", "Unknown")
            error = (detail.get("error") or "")[:100]
            success = detail.get("success", False)
            status = ":white_check_mark:" if success else ":x:"
            message = error if error else "Verification passed"
            fields.append({
                "type": "mrkdwn",
                "text": f"{status} *{cve_id}*\n{message}",
            })

        # Add fields in groups of 2 (Slack limit)
        for i in range(0, len(fields), 2):
            blocks.append({
                "type": "section",
                "fields": fields[i : i + 2],
            })

    # Add timestamp footer
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"Sent at {payload.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            }
        ],
    })

    slack_payload = {
        "blocks": blocks,
        "attachments": [{"color": config["color"], "blocks": []}],
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(webhook_url, json=slack_payload)
            if response.status_code == 200:
                logger.info(f"Slack alert sent: {payload.title}")
                return True
            else:
                logger.warning(
                    f"Slack webhook returned {response.status_code}: {response.text}"
                )
                return False
    except Exception as e:
        logger.exception(f"Failed to send Slack alert: {e}")
        return False


async def send_discord_alert(payload: AlertPayload) -> bool:
    """Send alert to Discord via webhook.

    Args:
        payload: Alert payload with title, message, severity, and optional details

    Returns:
        True if sent successfully, False otherwise
    """
    webhook_url = settings.discord_webhook_url
    if not webhook_url:
        logger.debug("Discord webhook not configured, skipping")
        return False

    # Map severity to color (Discord uses decimal colors)
    severity_colors = {
        "info": 0x2196F3,      # Blue
        "warning": 0xFFC107,   # Yellow/Orange
        "error": 0xF44336,     # Red
        "critical": 0x9C27B0,  # Purple
    }
    color = severity_colors.get(payload.severity, severity_colors["warning"])

    # Map severity to emoji
    severity_emoji = {
        "info": "ℹ️",
        "warning": "⚠️",
        "error": "❌",
        "critical": "🚨",
    }
    emoji = severity_emoji.get(payload.severity, "⚠️")

    # Build Discord embed
    embed = {
        "title": f"{emoji} {payload.title}",
        "description": payload.message,
        "color": color,
        "timestamp": payload.timestamp.isoformat(),
        "footer": {
            "text": "OctoLab CVE Verification",
        },
    }

    # Add details as fields if provided
    if payload.details:
        fields = []
        for detail in payload.details[:25]:  # Discord limit is 25 fields
            cve_id = detail.get("cve_id", "Unknown")
            error = detail.get("error") or ""
            success = detail.get("success", False)
            status = "✅" if success else "❌"
            duration = detail.get("duration_seconds", 0)

            # Truncate error to fit Discord field limit (1024 chars)
            error_short = error[:200] + "..." if len(error) > 200 else error

            fields.append({
                "name": f"{status} {cve_id} ({duration:.1f}s)",
                "value": error_short if error_short else "Verification passed",
                "inline": False,
            })

        embed["fields"] = fields

    discord_payload = {
        "embeds": [embed],
        "username": "OctoLab Alerts",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(webhook_url, json=discord_payload)
            if response.status_code in (200, 204):
                logger.info(f"Discord alert sent: {payload.title}")
                return True
            else:
                logger.warning(
                    f"Discord webhook returned {response.status_code}: {response.text}"
                )
                return False
    except Exception as e:
        logger.exception(f"Failed to send Discord alert: {e}")
        return False


async def send_alert(payload: AlertPayload) -> dict[str, bool]:
    """Send alert via all configured channels.

    Args:
        payload: Alert payload

    Returns:
        Dict with channel names and success status
    """
    results = {}

    # Send Slack alert
    if settings.slack_webhook_url:
        results["slack"] = await send_slack_alert(payload)

    # Send Discord alert
    if settings.discord_webhook_url:
        results["discord"] = await send_discord_alert(payload)

    if not results:
        logger.info("No notification channels configured")

    return results


async def send_cve_verification_report(
    total: int,
    passed: int,
    failed: int,
    errors: int,
    duration_seconds: float,
    details: list[dict[str, Any]],
) -> dict[str, bool]:
    """Send CVE verification report - always sends full results.

    Args:
        total: Total CVEs verified
        passed: Number that passed
        failed: Number that failed
        errors: Number with errors
        duration_seconds: Total verification time
        details: List of verification result dicts

    Returns:
        Dict with channel names and success status
    """
    if total == 0:
        logger.info("No CVEs verified, skipping report")
        return {}

    # Calculate pass rate
    pass_rate = (passed / total * 100) if total > 0 else 0

    # Determine severity based on pass rate
    if pass_rate == 100:
        severity = "info"
        status_emoji = "✅"
        status_text = "ALL PASSED"
    elif pass_rate >= 80:
        severity = "warning"
        status_emoji = "⚠️"
        status_text = "SOME FAILURES"
    else:
        severity = "critical"
        status_emoji = "🚨"
        status_text = "CRITICAL"

    # Format duration
    if duration_seconds >= 60:
        duration_str = f"{duration_seconds / 60:.1f}m"
    else:
        duration_str = f"{duration_seconds:.0f}s"

    # Build title with pass rate prominently displayed
    title = f"CVE Verification: {pass_rate:.0f}% Pass Rate ({passed}/{total})"

    # Build message
    message_lines = [
        f"**{status_emoji} {status_text}**",
        "",
        f"```",
        f"Pass Rate:  {pass_rate:5.1f}%  {'█' * int(pass_rate / 10)}{'░' * (10 - int(pass_rate / 10))}",
        f"Passed:     {passed:5d}",
        f"Failed:     {failed:5d}",
        f"Errors:     {errors:5d}",
        f"Duration:   {duration_str:>5}",
        f"```",
    ]

    payload = AlertPayload(
        title=title,
        message="\n".join(message_lines),
        severity=severity,
        details=details,  # Include ALL results
    )

    return await send_alert(payload)


# Keep old name as alias for backwards compatibility
send_cve_verification_alert = send_cve_verification_report


async def send_dockerfile_review_alert(
    review_id: str,
    cve_id: str,
    recipe_name: str,
    attempts: int,
    errors: list[str],
    confidence_score: int | None = None,
) -> dict[str, bool]:
    """Send alert when a Dockerfile is added to the review queue.

    Args:
        review_id: UUID of the review queue entry
        cve_id: CVE identifier
        recipe_name: Name of the recipe that failed
        attempts: Number of generation attempts
        errors: List of error messages
        confidence_score: LLM confidence score (0-100)

    Returns:
        Dict with channel names and success status
    """
    # Get admin URL from environment or use default
    import os
    admin_base_url = os.environ.get("OCTOLAB_ADMIN_URL", "http://localhost:3000")
    review_url = f"{admin_base_url}/admin/review/{review_id}"

    # Determine severity based on confidence score
    if confidence_score is not None:
        if confidence_score < 30:
            severity = "critical"
        elif confidence_score < 50:
            severity = "error"
        else:
            severity = "warning"
    else:
        severity = "error"

    # Build message
    message_lines = [
        f"**Recipe:** {recipe_name}",
        f"**Attempts:** {attempts}",
    ]

    if confidence_score is not None:
        message_lines.append(f"**LLM Confidence:** {confidence_score}%")

    if errors:
        message_lines.append("")
        message_lines.append("**Errors:**")
        for err in errors[:3]:  # First 3 errors
            # Truncate long errors
            err_short = err[:150] + "..." if len(err) > 150 else err
            message_lines.append(f"• {err_short}")
        if len(errors) > 3:
            message_lines.append(f"• ... and {len(errors) - 3} more")

    message_lines.append("")
    message_lines.append(f"[**Review in Admin Panel →**]({review_url})")

    payload = AlertPayload(
        title=f"Dockerfile Review: {cve_id}",
        message="\n".join(message_lines),
        severity=severity,
        details=[{
            "cve_id": cve_id,
            "review_url": review_url,
            "attempts": attempts,
            "confidence_score": confidence_score,
        }],
    )

    return await send_alert(payload)
