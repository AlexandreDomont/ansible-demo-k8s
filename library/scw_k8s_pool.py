#!/usr/bin/python
# -*- coding: utf-8 -*-

# Ansible 2.18+ / Python 3.9+
# Module optimisé pour gérer un pool Kapsule via l'API HTTP Scaleway.
# Points clés :
#  - Attente robuste (statuts imbriqués, conditions Ready, tailles atteintes, nœuds Ready)
#  - Arrêt anticipé en cas d'échec
#  - Diagnostics améliorés (dernier statut + observation optionnelle)
#  - Tolérance aux 404 transitoires pendant la création

DOCUMENTATION = r'''
---
module: scw_k8s_pool
short_description: Gérer un pool Kapsule (Scaleway) via l'API HTTP
options:
  region:
    type: str
    required: true
  project_id:
    type: str
    required: true
  cluster_id:
    type: str
    required: true
  name:
    type: str
    required: true
  node_type:
    type: str
    required: true
  size:
    type: int
  autoscaling:
    type: bool
    default: false
  min_size:
    type: int
  max_size:
    type: int
  container_runtime:
    type: str
    default: containerd
  root_volume_type:
    type: str
    default: l_ssd
  root_volume_size:
    type: int
  autohealing:
    type: bool
    default: true
  public_ip_disabled:
    type: bool
    default: false
  tags:
    type: list
    elements: str
  token:
    type: str
    no_log: true
  api_url:
    type: str
    default: https://api.scaleway.com
  state:
    type: str
    choices: [present, absent]
    default: present
  wait:
    type: bool
    default: true
  wait_timeout:
    type: int
    default: 600
  wait_interval:
    description: Intervalle (s) entre deux sondes d'état.
    type: int
    default: 5
  debug_poll:
    type: bool
    default: false
requirements:
  - requests
'''

RETURN = r'''
pool:
  description: Données du pool après opération (si présent).
  returned: success and state=present
  type: dict
changed:
  type: bool
'''

from ansible.module_utils.basic import AnsibleModule
import os
import time
import json

try:
    import requests
except Exception:
    requests = None


class ScalewayAPI:
    def __init__(self, api_url, token):
        self.api_url = api_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "X-Auth-Token": token,
            "User-Agent": "ansible-scw-k8s-pool/1.2"
        })

    def _url(self, region, cluster_id, path=""):
        base = f"{self.api_url}/k8s/v1/regions/{region}/clusters/{cluster_id}/pools"
        return base if not path else f"{base}/{path}"

    def list_pools(self, region, cluster_id):
        url = self._url(region, cluster_id)
        r = self.session.get(url, timeout=30)
        self._raise_for_status(r, "list pools")
        data = r.json()
        if isinstance(data, dict) and "pools" in data:
            return data["pools"]
        if isinstance(data, list):
            return data
        return []

    def get_pool(self, region, cluster_id, pool_id):
        url = self._url(region, cluster_id, pool_id)
        r = self.session.get(url, timeout=30)
        if r.status_code == 404:
            return None
        self._raise_for_status(r, "get pool")
        return r.json()

    def create_pool(self, region, cluster_id, payload):
        url = self._url(region, cluster_id)
        r = self.session.post(url, data=json.dumps(payload), timeout=30)
        self._raise_for_status(r, "create pool")
        return r.json()

    def patch_pool(self, region, cluster_id, pool_id, payload):
        url = self._url(region, cluster_id, pool_id)
        r = self.session.patch(url, data=json.dumps(payload), timeout=30)
        self._raise_for_status(r, "patch pool")
        return r.json()

    def delete_pool(self, region, cluster_id, pool_id):
        url = self._url(region, cluster_id, pool_id)
        r = self.session.delete(url, timeout=30)
        if r.status_code in (204, 404):
            return True
        self._raise_for_status(r, "delete pool")
        return True

    def _raise_for_status(self, resp, what):
        if 200 <= resp.status_code < 300:
            return
        try:
            j = resp.json()
        except Exception:
            j = {"message": resp.text}
        raise RuntimeError(f"API error on {what}: {resp.status_code} {j}")


def desired_payload(params):
    autoscaling = params["autoscaling"]
    payload = {
        "name": params["name"],
        "node_type": params["node_type"],
        "container_runtime": params["container_runtime"],
        "root_volume": {"type": params["root_volume_type"]},
        "autohealing": params["autohealing"],
        "public_ip_disabled": params["public_ip_disabled"],
        "project_id": params["project_id"],
    }
    if params.get("root_volume_size"):
        payload["root_volume"]["size"] = params["root_volume_size"]
    if params.get("tags"):
        payload["tags"] = params["tags"]

    if autoscaling:
        payload["autoscaling"] = True
        if params.get("min_size") is not None:
            payload["min_size"] = params["min_size"]
        if params.get("max_size") is not None:
            payload["max_size"] = params["max_size"]
    else:
        payload["autoscaling"] = False
        if params.get("size") is not None:
            payload["size"] = params["size"]
    return payload


def pool_matches(pool, params):
    def get(d, *keys, default=None):
        cur = d
        for k in keys:
            if cur is None or k not in cur:
                return default
            cur = cur[k]
        return cur

    if not pool:
        return False

    want = desired_payload(params)
    same = True
    same &= get(pool, "name") == want["name"]
    same &= get(pool, "node_type") == want["node_type"]
    same &= (get(pool, "container_runtime") == want["container_runtime"])
    same &= (get(pool, "root_volume", "type") == want["root_volume"]["type"])
    if "size" in want:
        same &= (get(pool, "size") == want["size"])
    if "autoscaling" in want:
        same &= (bool(get(pool, "autoscaling")) == bool(want["autoscaling"]))
    if want.get("autoscaling"):
        if "min_size" in want:
            same &= (get(pool, "min_size") == want["min_size"])
        if "max_size" in want:
            same &= (get(pool, "max_size") == want["max_size"])
    if "autohealing" in want:
        same &= (bool(get(pool, "autohealing")) == bool(want["autohealing"]))
    if "public_ip_disabled" in want:
        same &= (bool(get(pool, "public_ip_disabled")) == bool(want["public_ip_disabled"]))
    if "tags" in want:
        same &= sorted(get(pool, "tags", default=[])) == sorted(want["tags"])
    if "root_volume" in want and "size" in want["root_volume"]:
        same &= (get(pool, "root_volume", "size") == want["root_volume"]["size"])
    return same


# ===== Nouvelles fonctions utilitaires pour l'attente robuste =====
READY_VALUES = {"ready", "available", "running", "active", "stable"}
FAIL_VALUES = {"error", "failed", "degraded"}


def _as_lower_str(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v.lower()
    if isinstance(v, dict):
        # champs possibles: name/state/phase/status
        for k in ("name", "state", "phase", "status", "value"):
            if k in v and isinstance(v[k], str):
                return v[k].lower()
        # fallback: repr du dict
        return json.dumps(v).lower()
    return str(v).lower()


def _truthy(v):
    return str(v).lower() in ("true", "1", "yes", "ready")


def extract_status(pool):
    """Extrait un statut textuel robuste depuis la ressource du pool."""
    if not pool:
        return ""
    # parfois la réponse peut être emballée dans {"pool": {...}}
    if isinstance(pool.get("pool"), dict):
        pool = pool["pool"]

    # clés communes au 1er niveau
    for key in ("status", "pool_status", "phase"):
        if key in pool:
            return _as_lower_str(pool[key])
    # chemins imbriqués connus: status.name, status.state
    status_obj = pool.get("status")
    if isinstance(status_obj, dict):
        for k in ("name", "state", "phase", "status"):
            if k in status_obj:
                return _as_lower_str(status_obj[k])

    # conditions de type Ready
    for cond_key in ("conditions", "pool_conditions", "node_pool_conditions"):
        conds = pool.get(cond_key)
        if isinstance(conds, list):
            for c in conds:
                t = _as_lower_str(c.get("type"))
                s = _as_lower_str(c.get("status"))
                if t == "ready" and s in ("true", "1", "ready"):
                    return "ready"

    # boolean direct
    if _truthy(pool.get("ready")):
        return "ready"

    return ""


def nodes_ready(pool):
    """Heuristique: considère le pool prêt si tous les nœuds renvoyés sont Ready."""
    nodes = pool.get("nodes") or pool.get("node_pool_nodes")
    if not isinstance(nodes, list) or not nodes:
        return False
    all_ready = True
    for n in nodes:
        # champs possibles
        st = _as_lower_str(n.get("status"))
        if st in FAIL_VALUES:
            return False
        if st in READY_VALUES:
            continue
        # conditions côté nœud
        conds = n.get("conditions")
        if isinstance(conds, list):
            ready_cond = next((c for c in conds if _as_lower_str(c.get("type")) == "ready"), None)
            if ready_cond and _truthy(ready_cond.get("status")):
                continue
        all_ready = False
    return all_ready


def sizes_reached(pool):
    """Détermine si la taille désirée est atteinte (quand renseignée par l'API)."""
    if not pool:
        return False
    desired = pool.get("desired_size") or pool.get("desiredNodes") or pool.get("size")
    current = pool.get("current_size") or pool.get("currentNodes") or pool.get("size")
    # fallback: compter les nœuds
    if current is None:
        nodes = pool.get("nodes") or []
        try:
            current = len(nodes)
        except Exception:
            current = None
    try:
        return desired is not None and current is not None and int(current) >= int(desired)
    except Exception:
        return False


def wait_until(api, region, cluster_id, pool_id, desired_state, timeout, interval=5):
    """
    desired_state: "ready" (present) ou "absent".
    Retourne (ok: bool, last_status: str, last_snapshot: dict|None)
    """
    deadline = time.time() + timeout
    last_status = ""
    last_snapshot = None
    while time.time() < deadline:
        if desired_state == "absent":
            p = api.get_pool(region, cluster_id, pool_id)
            if p is None:
                return True, "absent", None
            time.sleep(interval)
            continue

        # desired_state == present/ready
        p = api.get_pool(region, cluster_id, pool_id)
        if p is None:
            # pendant la création on peut voir un 404 transitoire
            time.sleep(interval)
            continue
        last_snapshot = p
        st = extract_status(p)
        last_status = st or last_status
        if st in READY_VALUES or sizes_reached(p) or nodes_ready(p):
            return True, st or "ready", p
        if st in FAIL_VALUES:
            return False, st, p
        time.sleep(interval)
    return False, last_status, last_snapshot


def main():
    module = AnsibleModule(
        argument_spec=dict(
            region=dict(type='str', required=True),
            project_id=dict(type='str', required=True),
            cluster_id=dict(type='str', required=True),
            name=dict(type='str', required=True),
            node_type=dict(type='str', required=True),
            size=dict(type='int'),
            autoscaling=dict(type='bool', default=False),
            min_size=dict(type='int'),
            max_size=dict(type='int'),
            container_runtime=dict(type='str', default='containerd'),
            root_volume_type=dict(type='str', default='l_ssd'),
            root_volume_size=dict(type='int'),
            autohealing=dict(type='bool', default=True),
            public_ip_disabled=dict(type='bool', default=False),
            tags=dict(type='list', elements='str'),
            token=dict(type='str', no_log=True),
            api_url=dict(type='str', default='https://api.scaleway.com'),
            state=dict(type='str', choices=['present', 'absent'], default='present'),
            wait=dict(type='bool', default=True),
            wait_timeout=dict(type='int', default=600),
            wait_interval=dict(type='int', default=5),
            debug_poll=dict(type='bool', default=False),
        ),
        supports_check_mode=True
    )

    if requests is None:
        module.fail_json(msg="Le module Python 'requests' est requis sur le contrôleur pour scw_k8s_pool.")

    params = module.params
    token = params.get("token") or os.environ.get("SCW_SECRET_KEY")
    if not token:
        module.fail_json(msg="Aucun token API trouvé. Passez 'token=' ou exportez SCW_SECRET_KEY dans l'environnement.")

    region = params["region"]
    project_id = params["project_id"]
    cluster_id = params["cluster_id"]
    name = params["name"]
    state = params["state"]
    wait = params["wait"]
    wait_timeout = params["wait_timeout"]
    wait_interval = params["wait_interval"]

    api = ScalewayAPI(params["api_url"], token)

    try:
        pools = api.list_pools(region, cluster_id)
        cur_pool = next((p for p in pools if p.get("name") == name), None)
        cur_id = cur_pool.get("id") if cur_pool else None

        if state == "absent":
            if not cur_pool:
                module.exit_json(changed=False)
            if module.check_mode:
                module.exit_json(changed=True, pool=cur_pool)
            api.delete_pool(region, cluster_id, cur_id)
            if wait:
                ok, last, _ = wait_until(api, region, cluster_id, cur_id, "absent", wait_timeout, wait_interval)
                if not ok:
                    module.fail_json(msg=f"Timeout: le pool '{name}' n'a pas été supprimé dans les {wait_timeout}s.")
            module.exit_json(changed=True)

        # state == present
        spec = desired_payload(params)

        if not cur_pool:
            if module.check_mode:
                module.exit_json(changed=True, pool=dict(desired=spec))
            created = api.create_pool(region, cluster_id, spec)
            pool_id = created.get("id") or (created.get("pool") or {}).get("id")
            if wait and pool_id:
                ok, last, snap = wait_until(api, region, cluster_id, pool_id, "ready", wait_timeout, wait_interval)
                if not ok:
                    detail = dict(last_status=last or 'inconnu')
                    if params.get('debug_poll') and isinstance(snap, dict):
                        try:
                            detail['last_observation'] = {k: snap.get(k) for k in list(snap.keys())[:10]}
                        except Exception:
                            pass
                    module.fail_json(msg=f"Timeout: le pool '{name}' n'est pas prêt après {wait_timeout}s (dernier statut: {last or 'inconnu'}).", **detail)
            module.exit_json(changed=True, pool=created)

        # Déjà présent → comparer et patcher si nécessaire
        if pool_matches(cur_pool, params):
            module.exit_json(changed=False, pool=cur_pool)

        if module.check_mode:
            module.exit_json(changed=True, pool=dict(current=cur_pool, desired=spec))

        updated = api.patch_pool(region, cluster_id, cur_id, spec)
        if wait:
            ok, last, snap = wait_until(api, region, cluster_id, cur_id, "ready", wait_timeout, wait_interval)
            if not ok:
                detail = dict(last_status=last or 'inconnu')
                if params.get('debug_poll') and isinstance(snap, dict):
                    try:
                        detail['last_observation'] = {k: snap.get(k) for k in list(snap.keys())[:10]}
                    except Exception:
                        pass
                module.fail_json(msg=f"Timeout: le pool '{name}' n'est pas prêt après {wait_timeout}s (post-patch, dernier statut: {last or 'inconnu'}).", **detail)
        module.exit_json(changed=True, pool=updated)

    except Exception as e:
        module.fail_json(msg=str(e))


if __name__ == '__main__':
    main()
