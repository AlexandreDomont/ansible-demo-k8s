# 🚀 Demo Kubernetes avec Ansible (Scaleway Cluster Manager)

Ce dépôt permet de réaliser une **démo de bout en bout** :  
- **Création** d’un cluster Kubernetes géré via **Scaleway Cluster Manager**  
- **Récupération** du kubeconfig  
- **Vérification** du cluster  
- **Déploiement** d’une application avec Ansible

Modules utilisés :
- `scaleway_k8s_cluster` de la collection `scaleway.scaleway`
- `scw_k8s_pool`personnalisé pour gérer les pools k8s SCW API
- `kubernetes.core.k8s` de la collection `kubernetes.core`

> ✅ **Testé avec** : `ansible-core 2.15.x`

## 📁 Arborescence

```
.
├── ansible.cfg
├── artifacts
│   └── cluster_id.txt           # ID du cluster (persisté)
├── inventories
│   └── scw
│       ├── group_vars
│       │   └── all
│       │       └── secret.yml   # secrets chiffrés (Ansible Vault)
│       └── host.ini             # inventaire
├── library
│   └── scw_k8s_pool.py          # module custom Scaleway (si utilisé par tes playbooks)
├── playbooks
│   ├── creat-cluster-k8s.yml    # création du cluster
│   ├── deploy-app-k8s.yml       # déploiement applicatif
│   └── getconfig-k8s.yml        # récupération du kubeconfig
├── README
├── requirements.txt             # dépendances Python
└── requirements.yml             # collections Ansible Galaxy
```

## 🧰 Prérequis

- **Python** ≥ 3.9  
- **ansible-core 2.15.x**  
- **kubectl** dans le `PATH`  
- Un **compte Scaleway** + **clé API** (variables dans `secret.yml`, chiffré via Vault)

> Optionnel mais recommandé : utiliser un **virtualenv** (`python3 -m venv .venv && source .venv/bin/activate`).

## 📦 Dépendances

Installe **les collections Ansible** et **les libs Python** :

```bash
ansible-galaxy collection install -r requirements.yml
python3 -m pip install -r requirements.txt
```

> Les versions exactes sont gérées par `requirements.yml`/`requirements.txt`.  
> Exemple côté Python : `scaleway`, `kubernetes>=24.2.0`, `urllib3<3`.  
> Exemple côté Galaxy : `scaleway.scaleway`, `kubernetes.core`, `community.general`.

## 🔐 Secrets (Ansible Vault)

Place tes identifiants Scaleway dans `inventories/scw/group_vars/all/secret.yml` et **chiffre** le fichier :

```bash
ansible-vault encrypt inventories/scw/group_vars/all/secret.yml
head -n1 inventories/scw/group_vars/all/secret.yml
# -> $ANSIBLE_VAULT;1.1;AES256
```

Exemples de variables (à adapter) :

```yaml
access_key: xxxxxxxxxxxxx
secret_key: xxxxxxxxxxxxx
default_organization_id: xxxxxx
default_project_id: xxx
scw_private_network_id: xxx
scw_region: "xxx"
scw_token: "xxx"
```

> Le mot de passe Vault n’est **jamais** committé. Utilise `--ask-vault-pass` ou `--vault-id`.

## ▶️ Exécution (pas à pas)

1. **Créer le cluster**
   ```bash
   ansible-playbook playbooks/creat-cluster-k8s.yml -e cluster_name=demo-k8s-cluster  --ask-vault-pass
   ```
   - L’ID du cluster peut être écrit dans `artifacts/cluster_id.txt` (selon le playbook).

2. **Récupérer le kubeconfig**
   ```bash
   ansible-playbook playbooks/getconfig-k8s.yml --ask-vault-pass
   ```

3. **Vérifier le cluster**
   ```bash
   kubectl get nodes
   ```

4. **Déployer l’application**
   ```bash
   ansible-playbook playbooks/deploy-app-k8s.yml  --ask-vault-pass  -e scw_cluster_id="5317b6f1-4c39-40dd-a3cc-2909163326fd"
   ```
   > Si ton playbook a persisté l’ID du cluster :  
   > `-e scw_cluster_id="$(cat artifacts/cluster_id.txt)"`

## ⚙️ Inventaire & configuration

- **Inventaire** : `inventories/scw/host.ini` (ex. cible locale/contrôleur)
- **Configuration Ansible** : `ansible.cfg` (pipelining, inventaire par défaut, etc.)

Exemple minimal d’`ansible.cfg` :

```ini
[defaults]
inventory = inventories/scw/host.ini
host_key_checking = False
pipelining = True
retry_files_enabled = False
# Décommente si tu utilises un venv :
# interpreter_python = .venv/bin/python
```
## 🧪 Dépannage rapide

- **Erreur “Failed to import the required Python library (scaleway)”**  
  → Installe via `python3 -m pip install -r requirements.txt` (ou `pip install scaleway`).  
  → Vérifie que `ansible_python_interpreter` pointe vers l’interpréteur où la lib est installée.

- **Vault : modifier les secrets**  
  ```bash
  ansible-vault edit inventories/scw/group_vars/all/secret.yml
  ```

- **kubectl n’accède pas au cluster**  
  → Vérifie le kubeconfig généré (chemin, variable `KUBECONFIG`, droits).  
  → `kubectl config get-contexts` pour inspecter le contexte.

## 📝 Licence

Ce dépôt est distribué sous **licence MIT**.
