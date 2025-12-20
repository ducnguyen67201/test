"""NVD API client with database caching."""

import logging
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cve_metadata import CVEMetadata

logger = logging.getLogger(__name__)

NVD_API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"


async def get_cve_metadata(cve_id: str, db: AsyncSession) -> Optional[dict]:
    """Get CVE metadata from cache or NVD API."""
    cve_id = cve_id.upper()

    # 1. Check cache first
    result = await db.execute(
        select(CVEMetadata).where(CVEMetadata.cve_id == cve_id)
    )
    cached = result.scalar_one_or_none()

    if cached:
        logger.debug(f"NVD cache hit for {cve_id}")
        return _to_dict(cached)

    # 2. Fetch from NVD
    logger.info(f"Fetching {cve_id} from NVD API")
    data = await _fetch_from_nvd(cve_id)

    if data:
        # 3. Cache it
        await _cache_metadata(cve_id, data, db)
        return data

    return None


async def _fetch_from_nvd(cve_id: str) -> Optional[dict]:
    """Fetch CVE data from NVD API."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                NVD_API_URL,
                params={"cveId": cve_id},
            )

            if response.status_code == 200:
                return _parse_nvd_response(response.json())
            elif response.status_code == 404:
                logger.warning(f"CVE {cve_id} not found in NVD")
                return None
            else:
                logger.error(f"NVD API error: {response.status_code}")
                return None

    except Exception as e:
        logger.error(f"NVD fetch failed for {cve_id}: {e}")
        return None


def _parse_nvd_response(data: dict) -> Optional[dict]:
    """Parse NVD API response into structured data."""
    try:
        vulns = data.get("vulnerabilities", [])
        if not vulns:
            return None

        vuln = vulns[0]["cve"]

        # Get English description
        descriptions = vuln.get("descriptions", [])
        description = next(
            (d["value"] for d in descriptions if d["lang"] == "en"),
            descriptions[0]["value"] if descriptions else "",
        )

        # Get CVSS score (try v3.1, v3.0, v2 in order)
        metrics = vuln.get("metrics", {})
        cvss_data = {}
        for metric_key in ["cvssMetricV31", "cvssMetricV30", "cvssMetricV2"]:
            metric_list = metrics.get(metric_key, [])
            if metric_list:
                cvss_data = metric_list[0].get("cvssData", {})
                break

        # Get affected products from configurations
        affected = []
        for config in vuln.get("configurations", []):
            for node in config.get("nodes", []):
                for match in node.get("cpeMatch", []):
                    if match.get("vulnerable"):
                        affected.append({
                            "cpe": match.get("criteria", ""),
                            "versionStart": match.get("versionStartIncluding"),
                            "versionEnd": match.get("versionEndIncluding"),
                            "versionEndExcluding": match.get("versionEndExcluding"),
                        })

        # Get reference URLs (limit to 10)
        references = [ref["url"] for ref in vuln.get("references", [])][:10]

        return {
            "cve_id": vuln["id"],
            "description": description,
            "cvss_score": cvss_data.get("baseScore"),
            "cvss_severity": cvss_data.get("baseSeverity"),
            "affected_products": affected,
            "references": references,
        }

    except Exception as e:
        logger.error(f"Failed to parse NVD response: {e}")
        return None


async def _cache_metadata(cve_id: str, data: dict, db: AsyncSession):
    """Save CVE metadata to database cache."""
    entry = CVEMetadata(
        cve_id=cve_id,
        description=data.get("description"),
        cvss_score=data.get("cvss_score"),
        cvss_severity=data.get("cvss_severity"),
        affected_products=data.get("affected_products"),
        references=data.get("references"),
    )
    db.add(entry)
    await db.commit()
    logger.info(f"Cached NVD metadata for {cve_id}")


def _to_dict(cached: CVEMetadata) -> dict:
    """Convert cached model to dict."""
    return {
        "cve_id": cached.cve_id,
        "description": cached.description,
        "cvss_score": cached.cvss_score,
        "cvss_severity": cached.cvss_severity,
        "affected_products": cached.affected_products,
        "references": cached.references,
    }
