# Phone support / Appel agent in-app via WebRTC

> Brainstorm — choix d'une stack pour permettre à un end-user d'appeler un agent en direct depuis le widget Showdesk (audio, puis vidéo, puis PSTN, puis AI voice agent).
>
> Date de rédaction : 2026-05-01.

---

## TL;DR

- **Recommandation MVP : LiveKit Cloud (plan Ship $50/mo)**, SDK JS embarqué dans le widget, server SDK Python côté Django pour issuer les tokens, room par ticket. Audio-only en premier, ajout vidéo/screen share trivial puisque le SDK gère déjà ces tracks.
- **Justification courte** : LiveKit est l'open source de référence en 2025-2026 pour la temps-réel orientée AI agents, prix très agressif ($0.0005/min participant Ship → $0.0004/min Scale, 5x à 10x moins cher que Daily/Twilio/100ms à $0.004/min), SDK JS léger, recording (Egress) intégré, SIP intégré pour la roadmap PSTN, framework Agents 1.5 prêt pour le voice AI sans changer de provider, et option de self-host Helm sur k8s sans réécriture le jour où on veut quitter le cloud.
- **Stack à éviter pour Showdesk** : Twilio Programmable Video (rescapé d'un EOL annoncé pour décembre 2026 puis annulé — risque stratégique), Vonage/OpenTok (déclin, $0.00395/min, $500/mo monitoring add-on, design legacy), Agora (tarif HD 4-9x au-dessus de LiveKit, perception "gaming/social" plus que "B2B SaaS").
- **Coût estimé MVP** (1 000 min/mois audio-only, 1 agent + 1 enduser par appel = 2 000 participant-min) : **~$2/mois LiveKit overage** (gratuit sous le quota Ship) vs **$8/mois Daily.co** vs **$12/mois Vonage**. À 10 000 min/mois (20k participant-min) on reste largement sous les 150k min/mois inclus dans le plan Ship LiveKit ⇒ **$50/mo flat**.
- **Roadmap** : Phase 1 (audio in-app) → Phase 2 (vidéo + screen share + recording opt-in + transcription post-call Whisper/Deepgram) → Phase 3 (PSTN entrant via Twilio/Telnyx SIP trunk → LiveKit SIP → room) → Phase 4 (AI voice agent en first responder via LiveKit Agents + OpenAI Realtime + escalade humaine).
- **Compliance RGPD** : recording **OFF par défaut**, prompt explicite "Cet appel peut être enregistré pour améliorer la qualité du support — souhaitez-vous continuer ? Oui/Non" affiché dans le widget AVANT établissement de la connexion média (pas un disclaimer enfoui dans le ToS), legitimate interest docs côté Showdesk org, opt-out toujours possible, durée de rétention paramétrable par org (default 30 jours), accès audit log.

---

## 1. Comparatif des stacks WebRTC

### Tableau synthétique

| Stack | Prix audio (par participant-min) | Prix video | Recording | SIP/PSTN natif | AI agents natif | Self-host | Fit Showdesk |
|---|---|---|---|---|---|---|---|
| **LiveKit Cloud** | $0.0004–$0.0005/min | idem | $0.005/min audio, $0.015–$0.02/min video | Oui (LiveKit SIP, $0.003–$0.004/min + trunk Twilio/Telnyx) | Oui (Agents 1.5 framework, MCP tools, 50+ models) | Oui, Helm chart officiel, Go + Pion, Apache 2.0 | **Excellent — recommandé** |
| **Daily.co** | $0.00099/min audio, $0.004/min video | $0.004/min | $0.01349/min | Limité (Daily Bots) | Daily Bots récent | Non | Bon — UI prefab utile mais 8x cher en audio |
| **Twilio Programmable Video** | $0.0015–$0.004/min | idem | additionnel | Twilio Voice mature | Pas natif côté video | Non | Risqué — EOL annoncé puis annulé, signal stratégique négatif |
| **100ms** | $0.001/min audio, $0.004/min video | $0.004/min | additionnel | Limité | Non | Non | Bon mais pas de SIP/PSTN natif |
| **Stream Video** | $0.0003–$0.012/min selon résolution | idem | inclus partiellement | Non | Limité | Non | Intéressant si on bundlait chat+video Stream, mais on a déjà notre chat Channels |
| **Agora.io** | $0.99/1 000 min ($0.00099/min) audio | $3.99/1 000 min HD, $8.99/1 000 min FHD | additionnel | Oui mais cher | Limité | Non | Mauvais ratio prix/perception B2B SaaS startups |
| **Vonage Video API (ex-OpenTok)** | $0.00395/min | $0.00395/min | $500/mo monitoring add-on | Vonage Voice | Limité | Non | Déclin, legacy |
| **Whereby Embedded** | iframe turnkey, pricing custom (~$10/1 000 min) | idem | inclus | Non | Non | Non | Trop "iframe", on perd le contrôle UX intégré au widget |
| **mediasoup (self-host)** | gratuit en licence + infra | idem | à coder | à coder | à coder | C++ + Node, expertise WebRTC requise | Mauvais — 3-5 mois de dev avant parité avec LiveKit Cloud, pas de ROI à notre échelle |
| **Janus / Pion (self-host)** | gratuit + infra | idem | à coder | à coder | à coder | expertise très forte requise | Mauvais — idem mediasoup |

### Points clés par stack

**LiveKit** ([livekit.com/pricing](https://livekit.com/pricing))
- Plan Ship ($50/mo) : **150 000 WebRTC participant-min/mois inclus**, 5 000 agent session min, 5 000 recording min, 5 000 SIP min, 250 GB egress.
- Plan Scale ($500/mo) : 1,5M WebRTC min, 50 000 agent min, 50 000 recording min, 50 000 SIP min, 3 TB egress.
- Overage Ship : $0.0005/min WebRTC, $0.005/min recording, $0.004/min SIP, $0.12/GB egress.
- Pricing model récemment refondu (fin du "participant minute" pur, métrique plus alignée sur le compute réel), upstream bandwidth devenu **gratuit** ([blog.livekit.io](https://blog.livekit.io/the-end-of-participant-minute/)).
- Open source (Apache 2.0), serveur Go, SDK JS/iOS/Android/Flutter/React Native, server SDK Python (parfait pour Django), Egress pour recording S3/GCS/Azure, Ingress pour RTMP entrant, Agents framework 1.5 pour IA voice (avril 2026, Python, support MCP natif, semantic turn detection, plug-and-play 50+ modèles via LiveKit Inference).
- Self-host via Helm chart officiel, k8s GKE/EKS/DOKS supportés out-of-the-box, host networking obligatoire (1 pod LiveKit par node), **3-4 semaines de travail infra** pour atteindre parité fonctionnelle avec Cloud selon retours communauté.

**Daily.co** ([daily.co/pricing/video-sdk](https://www.daily.co/pricing/video-sdk/))
- 10 000 min gratuites / mois, puis $0.004/min vidéo, $0.00099/min audio.
- Recording $0.01349/min, transcription temps-réel $0.0059/min, post-call $0.0043/min.
- "Daily Prebuilt" UI iframe prête à l'emploi (utile pour PoC, pas pour widget intégré).
- Pas de SIP natif fort, pas d'open source.
- Bon outil, mais audio 2.5x plus cher que LiveKit Ship et **pas d'option self-host** le jour où on en a besoin.

**Twilio Programmable Video** ([twilio.com/en-us/video/pricing](https://www.twilio.com/en-us/video/pricing), [futurumgroup.com](https://futurumgroup.com/insights/twilio-drops-video-service-the-end-of-an-era-in-cpaas/))
- $0.0015–$0.004/min participant.
- **Risque stratégique** : Twilio a annoncé en mars 2024 un EOL au 5 décembre 2026, puis a fait machine arrière en 2025. Ce signal montre que le produit Video n'est pas le focus de Twilio — ne pas s'engager dessus pour un nouveau projet en 2026.
- Twilio Voice (PSTN) reste excellent et indépendant de cette histoire — utile potentiellement comme trunk SIP derrière LiveKit pour la phase PSTN.

**100ms.live** ([100ms.live/pricing](https://www.100ms.live/pricing))
- $0.001/min audio, $0.004/min video, 10 000 min gratuites.
- Bon prix audio mais pas de SIP/PSTN, pas d'agents AI natifs, pas de self-host.

**Vonage Video API** ([vonage.com](https://www.vonage.com/communications-apis/video/pricing/))
- $0.00395/min, **$500/mo "monitoring" add-on** quasi obligatoire pour debug en prod = killer pour une startup.
- Marque en déclin depuis le rachat d'OpenTok par Vonage.

**Agora.io** ([agora.io/en/pricing](https://www.agora.io/en/pricing/))
- HD $3.99/1 000 min (= $0.00399/min), FHD $8.99/1 000 min (= $0.00899/min).
- Très cher dès qu'on monte en résolution. Marché historique gaming/livestreaming/social plus que B2B SaaS.

**Stream Video** ([getstream.io/video/pricing](https://getstream.io/video/pricing/))
- $100/mo de crédit gratuit, puis $0.30 à $12 / 1 000 participant-min selon résolution.
- Intéressant **si** on adoptait toute la stack Stream (chat + video + feeds) — ce n'est pas notre cas, on a Django Channels pour le chat.

**mediasoup / Janus / Pion (self-host pur)**
- 0$ de licence, mais coût en ingénierie : 3-5 mois pour parité avec LiveKit OSS selon les retours communauté ([forasoft.com](https://www.forasoft.com/blog/article/livekit-ai-agents-guide), [trembit.com](https://trembit.com/blog/choosing-the-right-sfu-janus-vs-mediasoup-vs-livekit-for-telemedicine-platforms/)).
- À considérer **uniquement** si on dépasse $30k/mo de coûts SFU managé (ordre de grandeur cité par plusieurs sources), donc largement après notre PMF.

---

## 2. Recommandation principale : LiveKit Cloud (Ship), avec porte de sortie self-host

### Pourquoi LiveKit

1. **Prix imbattable à notre échelle** : à 1k–10k min/mois, on est gratuit ou quasi sur le plan Ship $50, là où Daily/Twilio/Vonage facturent $4–$40+ pour le même usage.
2. **Roadmap alignée sur la nôtre** :
   - Phase audio MVP → SDK JS, WebRTC pure.
   - Phase vidéo + screen share → activer une track vidéo + `screenShareTrack` du SDK, zéro changement d'infra.
   - Phase recording → API Egress (`POST /egress` côté server SDK Python), upload direct S3.
   - Phase PSTN → LiveKit SIP, derrière un trunk Twilio ou Telnyx, sans changer le runtime widget/agent.
   - Phase AI voice agent → LiveKit Agents framework Python, on peut reuser la même room et juste rajouter un participant agent IA.
3. **Open source Apache 2.0** : porte de sortie self-host quand le coût managé devient prohibitif. Le code du widget et du back-office ne change pas, seul le `LIVEKIT_URL` change.
4. **Server SDK Python natif** : s'intègre proprement à Django (génération de JWT room access tokens, webhooks pour `participant_joined`, `recording_finished`, etc.).
5. **AI Voice Agents 1.0+ matures** : framework Python avec semantic turn detection, MCP tools, plugins pour Deepgram, OpenAI Realtime, ElevenLabs, Anthropic, etc. Important pour notre roadmap "agent IA en first responder".

### Quand quitter LiveKit Cloud pour self-host

- Coût mensuel managé > $2 000–3 000/mois (équivaut à ~5–7 organizations payantes consommant intensivement la voix).
- Souverainenté/résidence des données exigée par un client gros compte (déjà couvert par tier Scale + EU region).
- Charge ingénierie acceptable : 3-4 semaines pour mettre en place le Helm chart sur notre k8s + Redis + recording S3 + monitoring.

---

## 3. Architecture proposée

```
┌────────────────────────────┐         ┌────────────────────────────┐
│  Widget (browser, embed)   │         │  Back-office agent (React) │
│  - bouton "Appeler"        │         │  - inbox tickets           │
│  - LiveKit JS SDK          │  WebRTC │  - LiveKit JS SDK          │
│  - audio/video tracks      │ <─────> │  - notif "appel entrant"   │
└──────────┬─────────────────┘   SFU   └──────────┬─────────────────┘
           │                                       │
           │ HTTPS (REST)                          │ WSS (Channels)
           v                                       v
┌─────────────────────────────────────────────────────────────────┐
│                  Django backend (showdesk)                       │
│                                                                  │
│  POST /api/widget/calls/request                                  │
│    - crée Call(ticket, status=requested)                         │
│    - choisit room name (ex: ticket-{uuid})                       │
│    - issue JWT LiveKit (room+identity+grants) via livekit-server-sdk
│    - notifie agents disponibles via Channels group               │
│    - retourne {room, token, livekit_url}                         │
│                                                                  │
│  POST /api/agent/calls/{id}/accept                               │
│    - assigne agent, issue JWT agent, status=in_progress          │
│                                                                  │
│  POST /webhooks/livekit (HMAC-signed)                            │
│    - participant_joined / participant_left → log                 │
│    - egress_ended → fetch S3 URL, attach to Ticket as attachment │
│                                                                  │
│  Celery tasks                                                    │
│    - post-call transcription (Deepgram async), update Ticket     │
│    - cost accounting per Organization                            │
└─────────────────────────────────────────────────────────────────┘
                               │
                ┌──────────────┴──────────────┐
                v                             v
     ┌────────────────────┐         ┌────────────────────┐
     │   LiveKit Cloud    │         │    S3 (recordings) │
     │  (or self-hosted   │ Egress  │    + Deepgram      │
     │   k8s + Redis)     │ ──────> │   (transcription)  │
     └────────────────────┘         └────────────────────┘
```

### Modèle de données (Django)

Nouvelle app `apps/calls/` (ou intégrée à `tickets`) :

```python
class Call(models.Model):
    organization = FK(Organization)
    ticket = FK(Ticket, null=True)  # créé/lié à la fin
    end_user = FK(EndUser, null=True)  # ou session widget
    requested_by_session_id = CharField()  # widget session
    accepted_by = FK(User, null=True)  # agent
    livekit_room = CharField(unique=True)
    status = Choices('requested', 'ringing', 'in_progress', 'completed', 'missed', 'rejected')
    started_at = DateTimeField(null=True)
    ended_at = DateTimeField(null=True)
    duration_seconds = IntegerField(default=0)
    recording_enabled = BooleanField(default=False)  # consent
    recording_s3_key = CharField(null=True)
    transcription_status = Choices('none', 'pending', 'done', 'failed')
    transcription_text = TextField(null=True)
    has_video = BooleanField(default=False)
    has_screen_share = BooleanField(default=False)
    metadata = JSONField()  # browser, page url, locale, etc.
```

### Signaling : qui joint en premier

- L'enduser appuie sur "Appeler" → `POST /widget/calls/request` → reçoit token room.
- Le serveur publie un event "call.requested" sur le group Channels `org_{id}_agents`.
- Le widget rejoint la room et attend (ringback audio local, pas besoin du SFU pour ça).
- Un agent disponible voit le toast, clique "Prendre l'appel" → `POST /agent/calls/{id}/accept` → reçoit token room.
- Quand le 2e participant rejoint, le SDK fait `room.on('participantConnected')` côté widget → on coupe le ringback et on connecte les tracks audio.
- Si aucun agent ne prend dans X secondes (90 par défaut, configurable par org) : `status=missed`, le widget propose "laisser un message vidéo" (lien avec la vidéothèque) ou "demander un rappel".

### Recording (Egress)

- Si `recording_enabled=True` (consent obtenu côté widget), on lance `RoomCompositeEgress` au moment où `accepted_by` est set. Output S3 (clé `org-{org_id}/calls/{call_id}.mp4` ou `.ogg` audio-only).
- Webhook `egress_ended` → on stocke `recording_s3_key`, on lance Celery `transcribe_call.delay(call_id)`.

### Transcription post-call

- **Choix recommandé : Deepgram Nova-3** pour le post-call. Latence pas critique en mode batch, mais qualité multilingue + diarization native + ~$0.0043/min en batch. Alternative : Whisper API OpenAI à $0.006/min, plus simple, qualité comparable mais pas de diarization fine.
- En **temps réel** (phase 4 quand on aura un agent IA dans le loop ou une transcription live affichée à l'agent humain), Deepgram streaming sub-300ms ou Gladia (~103ms partial latency, leader 2025-2026).

---

## 4. UX recommandée

### Côté widget (enduser)

**Pré-call**
- Bouton "Appeler un agent" visible quand l'org a la feature activée et qu'au moins 1 agent est `online` (pollé toutes les 30s côté widget, ou pushé via le WebSocket ticket existant).
- Si aucun agent dispo : libellé bouton devient "Demander un rappel" + petit formulaire (téléphone optionnel, message).
- Au clic : modal "Préparation de l'appel" avec :
  - Demande des permissions micro (et caméra plus tard).
  - Test rapide (vu-mètre micro local, indicateur "votre micro fonctionne").
  - Champ "Quel est le motif de votre appel ?" (pré-rempli si on est dans un ticket existant).
  - Checkbox "J'accepte l'enregistrement de l'appel pour amélioration du service" (RGPD, **non cochée par défaut**).
  - Bouton "Appeler maintenant".

**In-call**
- Avatar/initiales agent dès qu'il rejoint, avec son nom.
- Boutons : Mute, Toggle vidéo (si activée), Screen share (phase 2), Raccrocher.
- Indicateur réseau (latence, qualité).
- Zone "Notes / chat" repliable à droite pour passer en chat texte si la voix coupe.

**Post-call**
- "Comment évalueriez-vous cet appel ?" CSAT 1-5 étoiles.
- Création/lien automatique vers le ticket associé (si déjà ouvert) ou nouveau ticket avec resume auto-rédigé par GPT à partir de la transcription.
- Si recording activé : "Recevoir un résumé par email" (optionnel).

### Côté agent (back-office)

- **Indicateur de disponibilité** dans le sidebar : `Online / Busy / Offline`, avec horaires d'ouverture configurables par org (heures bureau, jours).
- **Toast notif** "Appel entrant — {nom user, page d'origine, motif}" avec boutons Prendre / Décliner.
- **Vue in-call** :
  - Vidéo de l'enduser (si activée), petite preview soi-même PiP.
  - Sidebar gauche : profil endcustomer, ticket courant, derniers tickets, logs widget récents.
  - Sidebar droite : prise de notes en live (sauvegardée auto sur le ticket), boutons Mute / Cam / Screen / Raccrocher.
  - Bouton "Transférer à un collègue" (sélection agent, le collègue rejoint la room et le 1er peut sortir).
- **Post-call** : modal de wrap-up forcée — disposition (résolu / à recontacter / escaladé), tags, note privée. Auto-fill possible depuis transcription.

### Disponibilité et fallback

- `OrganizationCallSettings` : `business_hours`, `auto_reply_after_hours`, `voicemail_enabled`, `max_queue_seconds`, `routing_strategy = round_robin | longest_idle | skill_based`.
- Hors horaires ou agents tous Busy : widget propose "laisser un message vidéo" (réutilise la vidéothèque + browser MediaRecorder, déjà partiellement codé d'après les memos), ou "demander un rappel" (formulaire async).
- Routing initial MVP : **longest-idle** (agent qui n'a pas pris d'appel depuis le plus longtemps), simple et juste. Skill-based en phase 3.

---

## 5. Roadmap

| Phase | Périmètre | Effort | Coût LiveKit estimé |
|---|---|---|---|
| **0 — Setup** | Compte LiveKit Cloud, Helm chart self-host stand-by, server SDK Python intégré, table `Call`, webhook signature HMAC | 1 semaine | Free (Build) |
| **1 — MVP audio** | Bouton appel, modal pré-call, signaling Channels, room audio-only, raccrocher, statut agent online/offline, table `Call` populée | 2 semaines | Free → $50/mo Ship |
| **2 — Vidéo + screen share + recording opt-in + transcription post-call** | Toggle cam, screen share, Egress S3, Deepgram batch, attachement au ticket, résumé GPT auto | 3 semaines | $50/mo + ~$5/mo Deepgram à 1k min |
| **3 — PSTN entrant** | Numéro DID Twilio/Telnyx par org, SIP trunk vers LiveKit SIP, IVR simple ("appuyez sur 1 pour le support"), voicemail si fermé | 4 semaines | $50–500/mo selon volume + ~$0.012/min Twilio FR inbound + DID ~$1/mo |
| **4 — AI voice agent en first responder** | LiveKit Agents Python + OpenAI Realtime (ou Deepgram + Anthropic) + RAG sur knowledge base org, escalade auto vers humain si confidence < seuil | 6 semaines | $0.06–0.30/min selon stack STT+LLM+TTS |
| **5 — PSTN sortant + multi-agent transfer + skill-based routing** | Click-to-call de l'agent vers un numéro tiers, conférences, skills tags | 4 semaines | + variable |

---

## 6. Considérations RGPD / consent / compliance

### Recording

- **Pas de recording par défaut**. Toggle org-level (`OrganizationCallSettings.recording_default`) + override par appel (consent user au moment du pré-call).
- **Information préalable obligatoire** (CNIL très stricte) : prompt clair "Cet appel peut être enregistré pour amélioration du service. Souhaitez-vous continuer ?" avec choix Oui / Non explicite — pas une checkbox enfouie. Le consent doit être **freely given, specific, informed** (CNIL).
- **Légal basis** : `Legitimate interest` documentable côté Showdesk org (mention dans la politique de confidentialité du site client) + consent explicite côté widget pour zéro ambiguïté.
- **Rétention** : durée par défaut 30 jours, configurable par org (max recommandé 6 mois sauf litige). Celery beat pour purge auto.
- **Accès** : seuls les agents et admins de l'org. Audit log de chaque écoute (qui, quand). Pas d'accès Showdesk staff sans demande explicite (sauf incident sécu).
- **Droit d'accès / suppression** : endpoint `DELETE /api/calls/{id}/recording` accessible à l'enduser via le widget (ou via demande email contact org). RGPD art. 17.
- **Stockage** : S3 EU region (eu-west-3 Paris ou eu-central-1 Frankfurt). Chiffrement at-rest SSE-S3 minimum, SSE-KMS recommandé. Pas de stockage US par défaut.

### Transcription

- Deepgram traite la donnée en EU si on prend le tier EU (à vérifier au sign-up). Sinon, Whisper local sur worker GPU possible mais coûteux.
- La transcription héritera de la même rétention que le recording.

### Métadonnées d'appel (durée, IP, browser)

- Conservées plus longtemps (12-24 mois) pour analytics et lutte anti-fraude — légitimate interest.

### Cas PSTN (phase 3)

- Identification appelant (CLI) : OK pour entrant, paramétrable en sortant (numéro principal de l'org).
- Régulation FR : pas de numéros surtaxés en first stage (08xx, 39xx) — DID classiques 09xx ou géographique. Vérifier eIDAS pour authentification renforcée si org dans secteur régulé (banque, santé).

---

## 7. Estimation de coûts

### Hypothèses

- 1 appel = 2 participants (1 enduser + 1 agent) = `duration × 2` participant-min.
- Durée moyenne d'appel support : 6 min (typique helpdesk B2B SaaS).
- Recording activé sur 30% des appels (consent user moyen).
- Transcription post-call activée sur 100% des recordings (utile au ticketing).

### Scénario A — Petite org, 1 000 minutes d'appel / mois

- 1 000 min × 2 = 2 000 participant-min/mois → **dans le quota Ship 150k**.
- Recording 300 min → **dans le quota Ship 5k**.
- Egress S3 ~3 GB → **dans le quota Ship 250 GB**.
- Deepgram batch 300 min × $0.0043 = **$1.29/mo**.
- **Total : ~$51/mo flat (Ship plan + Deepgram).**

### Scénario B — Org en croissance, 10 000 minutes d'appel / mois

- 10 000 min × 2 = 20 000 participant-min → **toujours dans Ship**.
- Recording 3 000 min → **dans Ship**.
- Egress ~30 GB → **dans Ship**.
- Deepgram batch 3 000 × $0.0043 = **$13/mo**.
- **Total : ~$63/mo (Ship + Deepgram).**

### Scénario C — Plusieurs orgs combinées, 100 000 minutes / mois

- 100 000 × 2 = 200 000 participant-min → 50 000 over Ship → $25 overage, mais à ce volume **passer Scale ($500/mo, 1.5M min inclus)**.
- Recording 30 000 min → 25 000 over Scale (50k inclus) → 0$ encore.
- Egress ~300 GB → dans Scale (3 TB).
- Deepgram batch 30 000 × $0.0043 = $129/mo.
- **Total : ~$629/mo Scale + Deepgram.**

### Scénario D — AI voice agent 10 000 min / mois (phase 4)

- LiveKit Agent session 10 000 min → 5 000 over Ship → $50 overage (à $0.01/min). Sinon plan Scale.
- OpenAI Realtime gpt-realtime : ~$0.06/min input + $0.24/min output ≈ **$0.30/min "all-in"** côté modèle.
- 10 000 min × $0.30 = **$3 000/mo de coûts AI** (sans LiveKit). C'est cohérent avec les benchmarks Vapi/Retell ($0.12–$0.35 all-in selon stack).
- **Insight clé** : à phase 4, le coût SFU (LiveKit) devient marginal (~5%), 95% du coût est sur les modèles AI. Choisir une stack hybride (Deepgram STT + Anthropic Sonnet + ElevenLabs TTS) peut diviser par 2-3 vs OpenAI Realtime.

### Comparaison stacks au scénario B (10 000 min / mois)

| Stack | Coût audio-only | Coût audio+vidéo |
|---|---|---|
| LiveKit Ship | **~$50/mo flat** | **~$50/mo flat** |
| Daily.co | ~$20/mo (audio $0.00099) | ~$80/mo (vidéo $0.004 × 20k) |
| Twilio Video | ~$80/mo | ~$80/mo |
| Vonage | ~$79/mo + $500 monitoring = **$579/mo** | idem |
| Agora HD | ~$20/mo | ~$80/mo |

→ LiveKit Ship gagne dès qu'on a >5 orgs actives ou qu'on active la vidéo.

---

## 8. Points de vigilance

- **Mobile WebRTC iOS Safari** : H.264-only, pas de simulcast complet, screen share limité, in-app browsers (WKWebView Instagram/Facebook) cassent souvent WebRTC. Tester tôt sur iOS réel. Pour la vidéo, forcer profil H.264 baseline. Pour les apps natives clients, prévoir une roadmap "SDK natif" plus tard.
- **Coût LiveKit Inference vs BYO models** : LiveKit Inference (Ship $5 ≈ 100 min) est très cher pour la prod. En prod, BYO API keys (OpenAI/Anthropic/Deepgram) directement.
- **Webhook security** : LiveKit signe ses webhooks en HMAC-SHA256, valider la signature dans la view Django.
- **Quotas free tier durs** : sur Build, capping à 5k WebRTC min. En dev/staging on consommera vite, prévoir un compte dédié dev distinct du compte prod.
- **Tenant isolation** : utiliser le pattern `room_name = f"org-{org_id}-call-{call_id}"` et issuer des tokens scoped à cette room. Ne JAMAIS donner un token avec `roomCreate=true` au widget.
- **Self-host k8s** : host networking obligatoire = 1 pod LiveKit par node, donc dimensionnement nodes ≠ dimensionnement pods classique. Plan attentif si on bascule.
- **Coût "cachée" du voice AI** : les benchmarks ($0.05–$0.07/min annoncés) ne couvrent que la layer orchestration. Coût réel all-in $0.12–$0.35/min. Modéliser avant de promettre un pricing flat aux clients.

---

## 9. Décisions à valider

1. **Stack** : LiveKit Cloud Ship MVP, self-host quand >$2k/mo. ✅ (recommandation)
2. **Recording** : opt-in user, off par défaut, S3 EU, rétention 30j. ✅
3. **Transcription** : Deepgram batch post-call MVP, streaming live en phase 4. À valider — alternative Whisper.
4. **PSTN** : Twilio Voice trunk derrière LiveKit SIP en phase 3. À valider vs Telnyx (moins cher, infra propre).
5. **AI agent** : LiveKit Agents framework en phase 4, BYO models (Deepgram + Anthropic + ElevenLabs probable plutôt que OpenAI Realtime full-stack pour le coût).
6. **Pricing produit Showdesk** : facturer le voice à part dans les plans (ex : 100 min/agent inclus dans Pro, $0.10/min au-delà avec marge sur LiveKit/Deepgram), ou inclure unlimited fair use ?

---

## Sources principales

- LiveKit pricing : [livekit.com/pricing](https://livekit.com/pricing), [End of participant-minute pricing (blog 2025)](https://blog.livekit.io/the-end-of-participant-minute/), [LiveKit knowledge base on cloud pricing](https://kb.livekit.io/articles/3947254704-understanding-livekit-cloud-pricing)
- LiveKit self-host k8s : [Helm chart docs](https://docs.livekit.io/transport/self-hosting/kubernetes/), [GitHub livekit/livekit](https://github.com/livekit/livekit), [KubeAce production guide](https://kubeace.com/blog/livekit-kubernetes-deployment/)
- LiveKit Agents : [GitHub livekit/agents](https://github.com/livekit/agents), [Forasoft 2026 playbook](https://www.forasoft.com/blog/article/livekit-ai-agents-guide), [LiveKit Agents docs](https://docs.livekit.io/agents/)
- LiveKit SIP : [SIP trunk setup docs](https://docs.livekit.io/telephony/start/sip-trunk-setup/), [Telnyx + LiveKit guide](https://developers.telnyx.com/docs/voice/sip-trunking/livekit-configuration-guide)
- LiveKit Egress / recording : [Egress overview](https://docs.livekit.io/home/egress/overview/), [GitHub livekit/egress](https://github.com/livekit/egress)
- Daily.co : [Video SDK pricing](https://www.daily.co/pricing/video-sdk/)
- Twilio Video : [Twilio Video pricing](https://www.twilio.com/en-us/video/pricing), [Standalone product changelog](https://www.twilio.com/en-us/changelog/-twilio-video-will-remain-a-standalone-product), [Futurum Group EOL coverage](https://futurumgroup.com/insights/twilio-drops-video-service-the-end-of-an-era-in-cpaas/)
- Twilio Voice France : [Programmable Voice France pricing](https://www.twilio.com/en-us/voice/pricing/fr)
- Telnyx vs Twilio : [Telnyx comparison](https://telnyx.com/resources/telnyx-vs-twilio-sip-trunking), [Plivo comparison](https://www.plivo.com/blog/telnyx-vs-twilio/), [Telnyx Elastic SIP pricing](https://telnyx.com/pricing/elastic-sip)
- 100ms : [100ms pricing](https://www.100ms.live/pricing)
- Vonage : [Vonage Video pricing](https://www.vonage.com/communications-apis/video/pricing/)
- Agora : [Agora pricing](https://www.agora.io/en/pricing/), [Video calling pricing docs](https://docs.agora.io/en/video-calling/overview/pricing)
- Stream Video : [Stream Video pricing](https://getstream.io/video/pricing/)
- Whereby Embedded : [Whereby Embedded pricing](https://whereby.com/information/embedded/pricing)
- mediasoup vs LiveKit : [Trembit comparison](https://trembit.com/blog/choosing-the-right-sfu-janus-vs-mediasoup-vs-livekit-for-telemedicine-platforms/), [Mylinehub comparison](https://mylinehub.com/articles/janus-vs-livekit-vs-mediasoup-webrtc-server-comparison)
- Deepgram / AssemblyAI / Gladia : [Gladia comparison](https://www.gladia.io/blog/assemblyai-vs-deepgram), [Deepgram pricing breakdown 2026](https://deepgram.com/learn/best-speech-to-text-apis-2026)
- OpenAI Realtime API : [OpenAI API pricing](https://openai.com/api/pricing/), [Introducing gpt-realtime](https://openai.com/index/introducing-gpt-realtime/)
- AI voice agents (Vapi/Retell/Bland) : [Retell AI 2026 pricing breakdown](https://www.retellai.com/blog/ai-voice-agent-pricing-full-cost-breakdown-platform-comparison-roi-analysis), [Edesy comparison](https://edesy.in/tools/voice-agent-pricing-comparison)
- WebRTC Safari iOS : [Antmedia 2026 browser support](https://antmedia.io/webrtc-browser-support/), [VideoSDK Safari guide](https://www.videosdk.live/developer-hub/webrtc/webrtc-safari)
- RGPD recording : [Salestrail GDPR call recording 2026](https://www.salestrail.io/blog/gdpr-and-call-recording-in-2026-how-to-track-calls-without-violating-privacy-laws), [GDPR Local recording rules](https://gdprlocal.com/gdpr-recording-calls/)
- Agent routing best practices : [WebRTC.ventures agent routing](https://webrtc.ventures/2023/11/implementing-agent-routing-in-web-applications/), [webrtcHacks contact center](https://webrtchacks.com/webrtc-contact-center/)
