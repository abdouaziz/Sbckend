# Feuille de route

Problèmes connus et améliorations prévues de l'API Kiriku, pour la plupart remontés par les équipes du challenge
Kiriku. Merci pour chaque retour : continuez à nous écrire dans le groupe du challenge, avec l'heure, la route, les
paramètres et le message d'erreur (jamais votre clé API).

**Statut :** 🔧 en cours · 📋 prévu · 🔎 à l'étude (faisabilité ou décision en attente) · ⏸️ pas encore disponible ·
✅ fait

## En un coup d'œil

| # | Sujet | Domaine | Statut | Origine |
|---|---|---|---|---|
| 1 | [Nombres lus en wolof](#1-nombres-lus-en-wolof) | Synthèse | 🔧 en cours | AI Hub, participants |
| 2 | [Liste des caractères lus, avertissement sur les ignorés](#2-caractères-lus-et-caractères-ignorés) | Synthèse | 📋 prévu | participants, 11/10 |
| 3 | [Synthèse qui boucle sur certains textes](#3-synthèse-qui-boucle-sur-certains-textes) | Synthèse | 🔎 exemples attendus | participants, 11/10 |
| 4 | [Lecture des lettres isolées (« AB », « BC »)](#4-lecture-des-lettres-isolées) | Synthèse | 📋 prévu (doc) | participants, 11/10 |
| 5 | [Voix sérère](#5-voix-sérère) | Synthèse | ⏸️ pas encore | participants |
| 6 | [Audio plus léger (mp3, opus)](#6-audio-plus-léger) | Synthèse | 📋 prévu | équipe |
| 7 | [Renvoyer la langue détectée](#7-renvoyer-la-langue-détectée) | Transcription | 🔎 à l'étude | participants, 10/10 |
| 8 | [Transcription plus rapide](#8-transcription-plus-rapide) | Transcription | 📋 prévu | équipe |
| 9 | [Utiliser les modèles hors du challenge](#9-utiliser-les-modèles-hors-du-challenge) | Documentation | 📋 prévu | participants, 11/10 |
| 10 | [Partage volontaire de données pour l'entraînement](#10-partage-volontaire-de-données-pour-lentraînement) | Données | 🔎 cadre d'abord | équipe |
| 11 | [Dépôt de référence public de Kiriku](#11-dépôt-de-référence-public-de-kiriku) | Dépôt | 🔎 décision d'AI Hub | équipe |
| 12 | [Déployer depuis un dépôt privé](#12-déployer-depuis-un-dépôt-privé) | Exploitation | 📋 prévu | équipe |
| 13 | [Nom de domaine stable](#13-nom-de-domaine-stable) | Exploitation | 🔎 à l'étude | équipe |
| 14 | [Rotation du fichier de logs](#14-rotation-du-fichier-de-logs) | Exploitation | 📋 prévu | équipe |
| 15 | [Quotas journaliers par clé](#15-quotas-journaliers-par-clé) | Exploitation | 📋 prévu | équipe |
| 16 | [Stockage partagé des clés](#16-stockage-partagé-des-clés) | Exploitation | 📋 si besoin | équipe |
| 17 | [Tests des routes avec modèles simulés](#17-tests-des-routes-avec-modèles-simulés) | Qualité | 📋 prévu | équipe |

[Déjà fait](#déjà-fait) : jetons de langue retirés des transcriptions, modèles chargés au démarrage, bornes de
`speed` et `503` en cas de mémoire GPU saturée, chiffres plus convertis en mots français.

---

## Synthèse vocale

### 1. Nombres lus en wolof

🔧 en cours · [PR #1](https://github.com/abdouaziz/Sbckend/pull/1)

- **Problème.** Les modèles lisent les chiffres de 0 à 9 mais sautent les nombres plus grands, absents de
  l'entraînement. Les écrire en mots français ne marche pas non plus : les voix wolof attendent du wolof (cette
  conversion a été retirée le 09/10/2026).
- **Prévu.** Un convertisseur de nombres en wolof bâti sur `num2words`, avec un mode pour compter (benn, ñaar,
  ñett…) et un mode pour les montants (dërëm, 1 dërëm = 5 FCFA), validé sur des exemples de référence fournis par un
  locuteur wolof ; puis le pulaar.
- **En attendant.** Écrire les nombres en toutes lettres, dans la langue de la voix.

### 2. Caractères lus et caractères ignorés

📋 prévu

- **Problème.** Tout caractère hors de l'alphabet de la voix est **ignoré sans avertissement** : les symboles
  (`+ = < > ° ²`…) disparaissent de l'audio sans erreur, et une équipe ne s'en rend compte qu'à l'écoute.
- **Faits** (vérifiés le 11/10/2026 dans [`mlroot/ww2`](https://huggingface.co/mlroot/ww2), révision `0558b7d`) :
  l'alphabet est dans le `config.json` de chaque voix, champs `characters` (lettres : 51 en wolof, 45 en pulaar,
  minuscules seulement) et `punctuations` (ponctuation et chiffres 0 à 9). `text_cleaner` est vide : l'API se
  contente de mettre le texte en minuscules.
- **Prévu.** (1) Renvoyer vers les deux fichiers depuis la documentation
  ([wolof](https://huggingface.co/mlroot/ww2/blob/main/checkpoints/wolof/config.json),
  [pulaar](https://huggingface.co/mlroot/ww2/blob/main/checkpoints/pulaar/config.json)). (2) Signaler à l'appelant
  les caractères ignorés, par exemple un en-tête de réponse `X-Skipped-Characters` donnant leur nombre, sans
  journaliser le texte.
- **Question ouverte.** Qu'un chiffre soit dans le vocabulaire ne prouve pas que le modèle le prononce : on nous a
  rapporté les deux. À trancher à l'écoute.

### 3. Synthèse qui boucle sur certains textes

🔎 exemples attendus

- **Problème.** La voix boucle parfois sur certains textes. Pas encore reproduit.
- **Étape suivante.** Recueillir 2 ou 3 textes qui le déclenchent, avec la voix, `speed` et `pitch`, puis
  reproduire. Une boucle consomme aussi du temps GPU : une fois la cause comprise, l'API devra borner la durée de
  l'audio par rapport à la longueur du texte.

### 4. Lecture des lettres isolées

📋 prévu (documentation)

- **Problème.** Les noms de lettres ne sont pas dans les données d'entraînement : « AB » passe en minuscules, « ab »,
  et se lit comme un mot. Les noms de points en géométrie (« AB », « BC ») et les sigles sont la principale source
  d'erreurs remontée.
- **Conseil aujourd'hui.** Écrire le nom de chaque lettre tel qu'il se prononce (« a bé », « bé sé »), avec une table
  de correspondance côté application, et garder la version qui sonne le mieux.
- **Prévu.** Ajouter ce conseil à *Good to know about the models*. Pas de table intégrée à l'API : certains sigles se
  lisent comme des mots (CEDEAO), d'autres doivent être épelés, et seule l'application sait lesquels.

### 5. Voix sérère

⏸️ pas encore disponible

- La transcription fonctionne en sérère, la synthèse non : il n'y a pas encore de voix sérère (confirmé par AI Hub le
  03/10/2026). Une requête avec `voice: "serer"` reçoit une erreur `400` explicite. L'ajouter ne demandera que le
  checkpoint, quand AI Hub en publiera un.

### 6. Audio plus léger

📋 prévu

- La synthèse ne renvoie que du WAV. Ajouter `mp3` et `opus` (`response_format`) pour réduire le temps de
  téléchargement, qui domine sur les phrases longues.

## Transcription

### 7. Renvoyer la langue détectée

🔎 à l'étude · décision : AI Hub

- **Demande.** Quand `language` est absent, renvoyer la langue détectée et, si possible, la probabilité de chaque
  langue candidate, comme le `verbose_json` d'OpenAI :
  `{"text": "…", "language": "wolof", "language_probability": 0.82, "language_probs": {…}}`. En option : préciser
  `language` resterait le comportement recommandé. Intérêt : l'utilisateur n'a plus à annoncer sa langue, et
  l'application peut gérer les cas d'hésitation.
- **Réserve (AI Hub).** Certaines langues sont proches, le sérère et le pulaar notamment : un audio en pulaar peut
  être transcrit en sérère, et inversement. D'où le conseil de toujours préciser `language`.
- **Faits.** Omettre `language` fonctionne déjà : le modèle choisit alors lui-même son jeton de langue (`<|wo|>`,
  `<|pu|>`, `<|se|>`), que l'API retire du texte (`backend/services/asr_text.py`). La langue détectée existe donc,
  mais elle est jetée, et une erreur de détection reste invisible pour l'appelant.
- **Faisabilité.** Renvoyer ce jeton dans `language` coûte peu. Les probabilités demandent les scores du décodeur
  sur les trois jetons de langue après `<|startoftranscript|>`, soit une étape de plus. La précision de la détection
  en pulaar et en sérère n'a **jamais été mesurée** : la mesurer d'abord sur de vrais enregistrements (l'équipe à
  l'origine de la demande a proposé les siens).

### 8. Transcription plus rapide

📋 prévu

- Passer à faster-whisper (CTranslate2) avec traitement par lots ; mesurer sur le GPU cible avant de l'adopter.
  Attention : le décodage haut niveau de faster-whisper jette les lettres ajoutées par l'affinage (`ŋ ɗ ɓ ƴ`) :
  appeler CTranslate2 directement et décoder avec le tokenizer du modèle.

## Documentation

### 9. Utiliser les modèles hors du challenge

📋 prévu

- **Question.** Quelles limites de débit et de durée envisager pour un usage en production ?
- **Réponse.** Cette API sert le challenge. En production, une équipe héberge les modèles sur sa propre
  infrastructure et fixe ses propres limites ; ce dépôt peut servir de point de départ (cf. sujet 11).
- **Prévu.** Le documenter, avec les licences : le checkpoint de la voix wolof est en **CC BY-NC 4.0** (pas d'usage
  commercial sans l'accord d'AI Hub) ; licence de la voix pulaar à confirmer ; M-Kiriku-ASR déclare `apache-2.0`.

## Données

### 10. Partage volontaire de données pour l'entraînement

🔎 décidé sur le principe, cadre d'abord

- **Quoi.** L'audio envoyé à la transcription avec le texte obtenu, et le texte envoyé à la synthèse ; pas le WAV
  synthétisé, qui n'est que la voix du modèle.
- **Avant tout code.** À qui appartient le jeu de données (AI Hub, Vie Publique), finalité, accès, durée de
  conservation, publication et licence, et validation juridique (la voix est une donnée personnelle : loi
  sénégalaise 2008-12, CDP).
- **Ensuite.** Un indicateur d'adhésion par clé, désactivé par défaut, activé depuis `/admin/ui` après accord écrit
  de l'équipe (aucune collecte rétroactive ; les équipes doivent avoir l'accord des personnes enregistrées) ; écriture
  après l'envoi de la réponse (aucun impact sur la latence) ; export régulier vers un stockage sûr (par exemple un
  dataset Hugging Face privé), car `/workspace` est lié à une machine ; suppression des données d'une équipe à sa
  demande.

## Dépôt et exploitation

### 11. Dépôt de référence public de Kiriku

🔎 en attente de la décision d'AI Hub

- Faire de ce dépôt l'intégration de référence de Kiriku, pour que chacun puisse le cloner et servir les modèles sur
  sa propre infrastructure. Avant de l'ouvrir : une `LICENSE` choisie par AI Hub (aucune aujourd'hui, donc aucune
  réutilisation autorisée), vérifiée contre les licences des modèles et de Coqui TTS (MPL-2.0) ; fusionner `test`
  dans `main` et en faire la branche par défaut (`dev` contient encore la première version) ; purger `.env` et
  `data/api_keys.db` de l'historique (`git filter-repo`, push forcé, coordonné avec tous ceux qui ont cloné) ; un
  guide de déploiement sur un pod RunPod et les variables d'environnement à jour. Puis déplacer le dépôt dans une
  organisation GitHub (AI Hub Senegal) plutôt qu'un compte personnel.

### 12. Déployer depuis un dépôt privé

📋 prévu

- Le pod RunPod récupère le code de façon anonyme au démarrage : cela ne marche que tant que le dépôt est public.
  Deux solutions : (1) un jeton GitHub à portée fine, créé par le propriétaire du dépôt, en lecture seule sur ce
  dépôt, passé au pod en `GITHUB_TOKEN` et utilisé dans l'URL de récupération, entouré de `set +x` pour qu'il
  n'apparaisse jamais dans les logs ; (2) mieux, une GitHub Action qui construit l'image à chaque push et la publie
  en privé sur GHCR, tirée par RunPod avec les identifiants du registre : redémarrage en quelques secondes au lieu
  de réinstaller les paquets, et une version fixe et reproductible.

### 13. Nom de domaine stable

🔎 à l'étude

- L'API répond sur l'URL brute de RunPod (`https://<pod>-8000.proxy.runpod.net`), qui change si le pod est recréé :
  chaque équipe devrait alors modifier son code. Un domaine à nous survivrait à un déménagement.

### 14. Rotation du fichier de logs

📋 prévu

- `logs/app.log` est écrit sans rotation à côté du code, sur le volume persistant (`/workspace/app/logs` sur le pod),
  et grossit donc indéfiniment. Le surveiller avec l'indicateur de disque du tableau de bord ; passer à un
  `RotatingFileHandler` (par exemple 3 × 10 Mo) s'il grossit.

### 15. Quotas journaliers par clé

📋 prévu

- Minutes d'audio et caractères par jour, en plus des limites de débit.

### 16. Stockage partagé des clés

📋 si besoin

- Les clés, l'usage et les limites de débit sont locaux à un processus : un stockage partagé ne sera nécessaire que
  si l'API tourne un jour sur plusieurs réplicas.

### 17. Tests des routes avec modèles simulés

📋 prévu

- Tester les routes avec des modèles simulés, au-delà des tests du middleware et de l'usage.

---

## Déjà fait

- ✅ **Jetons de langue retirés des transcriptions.** Le jeton par lequel le décodeur commence (`<|wo|>`…) se
  retrouvait parfois en tête du texte (2 clips wolof sur 8 dans notre banc), car `skip_special_tokens` ne couvre pas
  les jetons de langue ajoutés au tokenizer.
- ✅ **Modèles chargés au démarrage.** Chaque modèle se chargeait à la première requête qui en avait besoin (~30 s
  pour la première transcription après un redémarrage). Ils sont désormais chargés dans un fil séparé au démarrage,
  avec une inférence de chauffe chacun ; `/ping` répond `loading` jusqu'à ce qu'ils soient prêts.
- ✅ **Bornes de `speed` et mémoire GPU saturée** (09/10/2026, remonté par une équipe). En dessous de 0,5, l'audio
  grandissait sans limite : `speed=0` transformait une phrase de 27 caractères en plusieurs minutes d'audio et
  saturait la mémoire GPU. `speed` est désormais refusé en dessous de 0,5, et une mémoire GPU saturée renvoie `503`
  au lieu de `500`.
- ✅ **Chiffres plus convertis en mots français** (09/10/2026). Les voix wolof attendent du wolof : cf. sujet 1.
