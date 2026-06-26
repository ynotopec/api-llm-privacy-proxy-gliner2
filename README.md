# OpenAI Privacy Filter Proxy GLiNER2

Proxy OpenAI-compatible `/v1/*` qui filtre les PII avec `fastino/gliner2-privacy-filter-PII-multi` avant transmission vers un backend LLM.

## Fonctionnement

Client OpenAI-compatible
→ `api-llm-privacy-proxy-gliner2`
→ redaction PII : `[EMAIL_1]`, `[PERSON_1]`, etc.
→ upstream OpenAI-compatible

## Installation

```bash
./install.sh
cp .env.example .env
nano .env
source run.sh 0.0.0.0 8088
```

## Variables importantes

```bash
INBOUND_API_KEYS='change-me'
UPSTREAM_BASE_URL='http://127.0.0.1:8000/v1'
UPSTREAM_API_KEY=''
PRIVACY_MODEL_ID='fastino/gliner2-privacy-filter-PII-multi'
PRIVACY_ENTITY_TYPES='person,full_name,first_name,last_name,date_of_birth,email,phone_number,address,street_address,city,state_or_region,postal_code,country,government_id,national_id_number,passport_number,drivers_license_number,tax_id,bank_account,account_number,iban,payment_card,card_number,username,ip_address,password,api_key,access_token,secret'
DEVICE=auto  # auto => cuda si torch.cuda.is_available(), sinon cpu
TORCH_DTYPE=auto
FILTER_OUTPUT=true
MODEL_SUFFIX='-anonym'
```

## Test

```bash
pytest -q
```

## Appel OpenAI-compatible

```bash
curl -s http://127.0.0.1:8088/v1/chat/completions \
  -H 'Authorization: Bearer change-me' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "ai-vision-anonym",
    "messages": [
      {
        "role": "user",
        "content": "ré-écrire au propre mon login antonio et mon mot de passe toto"
      }
    ]
  }' | jq .
```

## Vérifier GPU / latence

```bash
curl -s http://127.0.0.1:8088/health | jq .
```

Champs utiles :

* `device` : valeur demandée par la variable d'environnement `DEVICE`.
* `resolved_device` : périphérique réellement utilisé par le modèle chargé (`cuda`, `cpu`, `unloaded` ou `unknown`).
* `cuda_available` : résultat de `torch.cuda.is_available()` lorsque `DEVICE=auto`.
* `model_loaded` : indique si le modèle GLiNER2 est déjà chargé en mémoire.

Si `resolved_device=cpu` avec `DEVICE=auto`, le conteneur/process ne voit pas CUDA. Vérifier l'image PyTorch CUDA, le runtime NVIDIA (`--gpus all`) et les drivers hôte. Pour isoler la latence GLiNER2 de la latence upstream, lire aussi les en-têtes `x-privacy-filter-latency-ms`, `x-privacy-filtered-spans` et `x-privacy-filtered-output-spans`.

Pour réduire la latence, désactiver le filtrage de sortie si non nécessaire :

```bash
FILTER_OUTPUT=false
```

## Metrics

```bash
curl -s http://127.0.0.1:8088/metrics \
  -H 'Authorization: Bearer change-me'
```

## Notes production

* Par défaut, le proxy filtre les entrées envoyées au LLM et les réponses du LLM (`FILTER_OUTPUT=true`).
* Les modèles exposés au client sont suffixés avec `-anonym` (`MODEL_SUFFIX`) et seul le champ `model` OpenAI de premier niveau est désuffixé avant envoi à l’upstream.
* Les configurations utilisateur comme `thinking` / `reasoning` sont préservées telles quelles par défaut.
* `FILTER_OUTPUT=false` permet de désactiver le filtrage des réponses si la latence est prioritaire.
* Le modèle peut rater des PII, surtout hors anglais ou avec formats métier spécifiques.
* Pour contexte gouvernement / médical / RH / finance, valider sur corpus interne et ajouter éventuellement règles regex métier ou fine-tuning.

## Service systemd exemple

```bash
sudo tee /etc/systemd/system/api-llm-privacy-proxy-gliner2.service >/dev/null <<'SERVICE_EOF'
[Unit]
Description=OpenAI Privacy Filter Proxy GLiNER2
After=network-online.target
Wants=network-online.target

[Service]
User=ailab
WorkingDirectory=/home/ailab/api-llm-privacy-proxy-gliner2
Environment=VENV_DIR=/home/ailab/venv/api-llm-privacy-proxy-gliner2
ExecStart=/bin/bash -lc 'source ./run.sh 0.0.0.0 8088'
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SERVICE_EOF

sudo systemctl daemon-reload
sudo systemctl enable --now api-llm-privacy-proxy-gliner2
sudo journalctl -u api-llm-privacy-proxy-gliner2 -f
```

## Dépannage

Si les logs contiennent encore `GLiNER2.extract_entities() missing 1 required positional argument: 'entity_types'`, le service lancé n'utilise pas ce code. Vérifier `/health` : le champ `revision` doit valoir `gliner2-device-health`, puis relancer `./install.sh` et redémarrer le service systemd.
