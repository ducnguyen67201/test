"""
DEPRECATED (2024-12-14): This module is not used.
Replaced by compose_runtime.py which provides better isolation and features.
Keeping for reference - may be useful for understanding the original MVP design.
"""
from __future__ import annotations

import asyncio
from typing import Optional
from uuid import UUID

import docker
from docker.errors import NotFound, APIError

from app.models.lab import Lab
from app.models.recipe import Recipe


class DockerHostRuntime:
    """
    MVP runtime that talks directly to the local Docker daemon.

    Assumptions:
    - Single lab host
    - Single concurrent lab (we won't enforce that here yet)
    - Images already built & present locally
    """

    def __init__(
        self,
        octobox_image: str = "octolab/octobox:latest",
        gateway_image: str = "octolab/lab-gateway:latest",
        target_image: str = "httpd:2.4",  # demo target
        pcap_volume: str = "lab_pcap",
    ) -> None:
        # NOTE: This is the *sync* Docker client.
        self._client = docker.from_env()
        self.octobox_image = octobox_image
        self.gateway_image = gateway_image
        self.target_image = target_image
        self.pcap_volume = pcap_volume

    # ---- public API (async wrappers over sync calls) ----

    async def create_lab(self, lab: Lab, recipe: Recipe) -> None:
        await asyncio.to_thread(self._create_lab_sync, lab, recipe)

    async def destroy_lab(self, lab: Lab) -> None:
        await asyncio.to_thread(self._destroy_lab_sync, lab)

    # ---- internal sync implementation ----

    def _create_lab_sync(self, lab: Lab, recipe: Recipe) -> None:
        lab_id_str = str(lab.id)
        network_name = self._network_name(lab.id)

        # 1. Ensure network exists
        network = self._ensure_network(network_name)

        # 2. Start target container first (simplest)
        target_container = self._create_target_container(lab_id_str, network_name)

        # 3. Start gateway (pcap capture)
        gateway_container = self._create_gateway_container(lab_id_str, network_name)

        # 4. Start OctoBox (noVNC on 6080)
        octobox_container = self._create_octobox_container(lab_id_str, network_name)

        # If we reach here without exceptions, containers are up.
        # Any exception will bubble and we let the caller mark lab as failed and maybe call destroy_lab.
        # We could add health checks later.

    def _destroy_lab_sync(self, lab: Lab) -> None:
        lab_id_str = str(lab.id)
        network_name = self._network_name(lab.id)

        # Best-effort stop/remove containers
        for cname in [
            self._octobox_name(lab_id_str),
            self._gateway_name(lab_id_str),
            self._target_name(lab_id_str),
        ]:
            try:
                container = self._client.containers.get(cname)
            except NotFound:
                continue
            try:
                container.stop(timeout=10)
            except APIError:
                # Ignore stop errors, try remove anyway
                pass
            try:
                container.remove(force=True)
            except APIError:
                # Best effort
                pass

        # Remove network
        try:
            network = self._client.networks.get(network_name)
            network.remove()
        except NotFound:
            pass
        except APIError:
            # Best effort
            pass

    # ---- helpers ----

    def _ensure_network(self, network_name: str):
        try:
            return self._client.networks.get(network_name)
        except NotFound:
            return self._client.networks.create(
                name=network_name,
                driver="bridge",
                labels={"octolab.lab_network": "true"},
            )

    def _create_target_container(self, lab_id: str, network_name: str):
        name = self._target_name(lab_id)
        return self._client.containers.run(
            self.target_image,
            name=name,
            detach=True,
            network=network_name,
            # expose port 80 inside lab; no host port mapping needed, OctoBox sees it by IP
            labels={
                "octolab.lab_id": lab_id,
                "octolab.role": "target",
            },
        )

    def _create_gateway_container(self, lab_id: str, network_name: str):
        name = self._gateway_name(lab_id)
        return self._client.containers.run(
            self.gateway_image,
            name=name,
            detach=True,
            network=network_name,
            environment={
                "LAB_ID": lab_id,
            },
            volumes={
                self.pcap_volume: {
                    "bind": "/pcap",
                    "mode": "rw",
                }
            },
            cap_add=["NET_ADMIN", "NET_RAW"],
            labels={
                "octolab.lab_id": lab_id,
                "octolab.role": "gateway",
            },
        )

    def _create_octobox_container(self, lab_id: str, network_name: str):
        name = self._octobox_name(lab_id)
        # Bind only to localhost for dev
        ports = {"6080/tcp": ("127.0.0.1", 6080)}
        return self._client.containers.run(
            self.octobox_image,
            name=name,
            detach=True,
            network=network_name,
            environment={
                "LAB_ID": lab_id,
            },
            ports=ports,
            labels={
                "octolab.lab_id": lab_id,
                "octolab.role": "octobox",
            },
        )

    # ---- naming helpers ----

    def _network_name(self, lab_id: UUID) -> str:
        return f"octolab_lab_{lab_id}"

    def _octobox_name(self, lab_id_str: str) -> str:
        return f"octolab_octobox_{lab_id_str}"

    def _gateway_name(self, lab_id_str: str) -> str:
        return f"octolab_gateway_{lab_id_str}"

    def _target_name(self, lab_id_str: str) -> str:
        return f"octolab_target_{lab_id_str}"
