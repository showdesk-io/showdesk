# Vidéothèque interne style Loom — Synthèse de recherche

> Brainstorm — mai 2026
> Objectif: permettre aux agents de Showdesk de créer des vidéos courtes (screen + webcam + audio) depuis le navigateur, sans Loom/Vidyard externe, et de les diffuser dans les tickets, la KB, le portail et les emails.

---

## TL;DR

1. **Faisabilité 100% web: oui pour le MVP** — `getDisplayMedia` + `getUserMedia` + `MediaRecorder` couvrent 90% du besoin sur Chrome/Edge/Firefox desktop. Il existe **deux trous fonctionnels** vs Loom Desktop: l'audio système sur **Safari macOS** (impossible navigateur) et la qualité d'encodage live sur **5K/4K** (encoder errors). Pour ces cas, la roadmap prévoit une extension Chrome puis (si traction) une app Tauri/Electron.
2. **Stack recommandée**: enregistrement navigateur (`MediaRecorder` + canvas PIP) → upload **tus.io** → **Cloudflare Stream** pour transcoding, HLS, signed URLs, GIF preview, clipping serveur, watermark. Player **Vidstack** (successeur de Plyr). Transcription **OpenAI gpt-4o-mini-transcribe** (0,18 $/h) avec fallback Whisper local.
3. **Coût total** (estimation pour 1 000 vidéos/mois, ~5 min, ~50 vues chacune):
   - Build interne (R2 + Lambda FFmpeg + CloudFront): ~25–40 $/mois en infra + dette de maintenance ~2-4 j-h/mois
   - **Cloudflare Stream**: ~80 $/mois (5 000 min stockées + 250 000 min livrées) — recommandé pour MVP
   - Mux: ~150–200 $/mois pour le même volume
4. **Roadmap**: MVP en ~6 sem (record + Cloudflare Stream + player + insert dans ticket reply). v2 = transcription, sous-titres, chapitres, KB embed, GIF preview email. v3 = analytics watch-time, traduction multilingue, extension Chrome.
5. **Risques majeurs**: (a) audio système Safari = pas de solution navigateur — accepter la limitation ou faire desktop app; (b) tailles vidéos non transcodées (>500 Mo pour 10 min en VP9) = upload résumable obligatoire; (c) coût bande passante si succès viral (un tutoriel KB qui prend → bascule sur Cloudflare Stream rentable car forfait minute, pas Go).

---

## 1. Faisabilité technique 100% web

### 1.1 APIs navigateur disponibles

| API | Rôle | Chrome/Edge | Firefox | Safari (16.4+) |
|---|---|---|---|---|
| `getDisplayMedia()` | Capture écran/fenêtre/onglet | Picker complet (display, window, tab) + tab-audio | Display + window seulement | Display courant uniquement, **pas de picker** |
| `getUserMedia()` | Webcam + micro | Oui | Oui | Oui |
| `MediaRecorder` | Encode MediaStream → blob | VP8/VP9/H264/AV1 + Opus | VP8/VP9 + Opus (codecs MIME diffèrent) | H264 + AAC (WebM partiel) |
| `canvas.captureStream()` | Composer stream custom (PIP webcam sur screen) | Oui | Oui | Oui |
| Audio système via `getDisplayMedia({audio:true})` | Capture son OS | **Chrome 141+ macOS 14.2+, OK Windows** | Partiel (tab audio) | **Non supporté** |

Sources principales: [MDN MediaRecorder](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder), [caniuse getDisplayMedia](https://caniuse.com/?search=getDisplayMedia), [Mozilla canvas captureStream](https://blog.mozilla.org/webrtc/enhancing-webcam-using-capturestream/), [addpipe Chrome macOS system audio](https://blog.addpipe.com/getdisplaymedia-allows-capturing-the-screen-with-system-sounds-on-chrome-on-macos/).

### 1.2 Composition PIP webcam-sur-écran (déjà partiellement codée dans le widget)

Le widget Showdesk possède déjà `widget/src/recorder/pip-compositor.ts` et `screen-recorder.ts` — la même logique se réutilise côté agent.

Pattern standard:
1. `screen = await getDisplayMedia({video, audio})` 
2. `cam = await getUserMedia({video, audio})`
3. Dessiner les deux dans un `<canvas>` à 30 fps (screen plein cadre + webcam ronde 200 px en bas-droite)
4. `composedStream = canvas.captureStream(30)` + ajouter les pistes audio mixées via `AudioContext`
5. `new MediaRecorder(composedStream, { mimeType: 'video/webm;codecs=vp9,opus', videoBitsPerSecond: 4_000_000 })`
6. Sur `dataavailable`: chunks de 5–10 s envoyés en streaming au backend (upload pendant l'enregistrement = perçu instantané à la fin).

### 1.3 Codecs: choix recommandé

- **Recording (browser)**: VP9 + Opus en WebM (best ratio Chrome/Firefox). Fallback H264+AAC pour Safari.
- **Delivery (player)**: HLS avec H.264 (compatibilité totale) + AV1 en rendition HD pour les viewers récents (-30 à -50% poids vs VP9, mais Safari AV1 = M3+ uniquement).
- Sources: [MDN Web video codec guide](https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Formats/Video_codecs), [Uploadcare codec landscape 2025](https://uploadcare.com/blog/navigating-codec-landscapes/).

### 1.4 Limites par navigateur — verdict

| Cas | Web seul OK ? | Workaround |
|---|---|---|
| Screen + webcam + mic | Oui partout | — |
| Audio système Windows | Oui (Chrome/Edge) | — |
| Audio système macOS | Oui (Chrome 141+, macOS 14.2+) | Avant: extension Chrome ou app desktop |
| Audio système Safari | **Non** | App desktop ou extension non disponible (Safari ext = limitée) |
| Picker fenêtre Safari | **Non** (display entier seulement) | Workaround UX: prévenir l'utilisateur |
| Recording 5K/4K | Risqué (`EncodingError`) | Cap à 1440p + warning |
| Recording > 30 min en mémoire | Risqué (RAM) | Streaming upload des chunks (déjà standard) |

**Conclusion: 100% web est la bonne stratégie pour le MVP.** Une fraction des agents (utilisateurs Safari macOS qui ont besoin d'audio système) sera en mode dégradé, on documente la limitation.

Sources: [Apple Safari WebRTC](https://www.zegocloud.com/blog/apple-safari-webrtc), [DEV system audio in browser](https://dev.to/flo152121063061/i-tried-to-capture-system-audio-in-the-browser-heres-what-i-learned-1f99).

---

## 2. Comparatif Loom / Vidyard / Tella / Scribe / Cap

### 2.1 Tableau forces/faiblesses

| Outil | Modèle | Architecture | Points forts | Points faibles | Pricing 2026 |
|---|---|---|---|---|---|
| **Loom** (Atlassian) | SaaS | Desktop app + Chrome ext + web | Marque, intégrations Jira, AI summary, qualité audio (desktop) | Cher post-acquisition Atlassian, modèle Creator seat | ~12-15 $/Creator/mois Business, 18-24 $ Business+AI |
| **Vidyard** | SaaS | Desktop app + ext + web | Sales-oriented, CRM intégrations, analytics enterprise | Cher, complexe | Plans pro 19+ $ |
| **Tella** | SaaS | Web pur (PWA) | UX moderne clip-based, transitions, captions sync | Moins d'intégrations | ~19-25 $/mois |
| **Scribe** | SaaS | Ext Chrome surtout | AI step-by-step guides (capture screen + texte auto) | Pas vraiment vidéo, plutôt doc | 23 $/user, 12 $/team min 5 |
| **Guidde** | SaaS | Ext + AI | Génère structured guides + voiceover IA | Niche | Plans similaires |
| **Cap** | OSS (MIT) | App desktop (Tauri) + dashboard web | Self-hostable, S3 custom, MIT, performant | Pas web pur, encore jeune | Free (self-host) ou cloud |

Sources: [Tella vs Loom](https://www.albertodirisio.com/tella-vs-loom/), [Vidyard vs Loom Arcade](https://www.arcade.software/post/vidyard-vs-loom), [Guidde alt comparisons](https://www.guidde.com/tool-comparison/scribe-vs-tella-pricing-comparison-2026), [Cap GitHub](https://github.com/CapSoftware/Cap), [Loom pricing 2026](https://www.atlassian.com/software/loom/pricing).

### 2.2 Pourquoi Loom maintient une desktop app

Trois raisons techniques:
1. **Audio système macOS** — la seule façon de capter le son d'apps tierces sur Mac sans Chrome 141+ (et même là, un user Safari n'aura jamais cette feature).
2. **Qualité d'encodage** — un encodeur natif (AVFoundation, MediaFoundation) est plus stable que `MediaRecorder` sur recordings longs/HD.
3. **Lancement raccourci clavier global** — un agent qui démarre une vidéo en `⌘⇧L` depuis n'importe quelle app vs ouvrir un onglet.

**Pour Showdesk**: le contexte est différent. Nos agents sont dans Showdesk déjà. Le bouton "Enregistrer" est dans le composer ticket. Pas besoin d'app desktop pour le 90/10. On peut viser 100% web et **assumer** qu'un user Safari mac qui veut audio système se débrouille (rare en B2B SaaS, et c'est documenté).

---

## 3. Stack technique recommandée

### 3.1 Architecture cible

```
┌──────────────────────────────────────────────────────────────┐
│  Browser (agent)                                             │
│  ├─ Recorder UI (React, déjà partiellement dans widget)      │
│  ├─ MediaRecorder → chunks WebM VP9                          │
│  └─ Upload tus.io (résumable, parallèle pendant le record)   │
└──────────────────────────────────────────────────────────────┘
         │ tus protocol (HTTPS PATCH)
         ▼
┌──────────────────────────────────────────────────────────────┐
│  Backend Django                                              │
│  ├─ tus endpoint (django-tus ou tusd reverse-proxy)          │
│  ├─ POST chunk to Cloudflare Stream tus endpoint            │
│  ├─ Webhook handler (status: ready)                          │
│  └─ Trigger transcription (Celery → OpenAI gpt-4o-mini-tx)   │
└──────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────┐
│  Cloudflare Stream                                           │
│  ├─ Auto transcoding (HLS multi-bitrate)                     │
│  ├─ Storage minute-based                                     │
│  ├─ Signed URLs (JWT)                                        │
│  ├─ Thumbnails + GIF previews + storyboard                   │
│  ├─ Server-side clipping (trim sans re-upload)               │
│  └─ CDN global                                               │
└──────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────┐
│  Player Vidstack (React)                                     │
│  ├─ HLS adaptive                                             │
│  ├─ Speed, captions, chapters, CTA                           │
│  └─ Branding Showdesk + watermark Org                        │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 Justification des choix

- **Cloudflare Stream** plutôt que self-hosted FFmpeg pour le MVP: encoding inclus, HLS auto, GIF/storyboard auto, [clipping API sans re-upload](https://developers.cloudflare.com/stream/edit-videos/video-clipping/), [signed URLs JWT](https://developers.cloudflare.com/stream/viewing-videos/securing-your-stream/), CDN inclus. Pas de Lambda à maintenir, pas de cold-storage à gérer. Pricing prévisible: 5 $/1000 min stockées + 1 $/1000 min livrées ([Cloudflare Stream pricing](https://developers.cloudflare.com/stream/pricing/)).
- **tus.io** plutôt que multipart S3 brut: chunk size flexible, vraie reprise, support Cloudflare Stream natif via [tus endpoint](https://developers.cloudflare.com/stream/uploading-videos/resumable-uploads/), client Uppy battle-tested. Source: [tus.io FAQ](https://tus.io/faq).
- **Vidstack** plutôt que Video.js: API moderne, hooks React natifs, successeur officiel de Plyr, taille bundle plus petite, bonne accessibilité. Source: [Vidstack player](https://vidstack.io/), [Croct comparison](https://blog.croct.com/post/best-react-video-libraries).
- **OpenAI gpt-4o-mini-transcribe** pour la transcription: 0,003 $/min = 0,18 $/h, qualité comparable à Whisper, 50+ langues. Pour les langues exotiques + code-switching → **Gladia** (100+ langues). Sources: [OpenAI pricing](https://openai.com/api/pricing/), [Gladia best speech-to-text](https://www.gladia.io/blog/best-speech-to-text-apis).

### 3.3 Alternative "build complet"

Si on veut éviter Cloudflare Stream:
- **Storage**: Cloudflare R2 (0,015 $/Go, **egress gratuit**) — c'est le killer feature pour la diffusion vidéo
- **Transcoding**: AWS Lambda + FFmpeg (~1,9% du coût d'Elastic Transcoder) ou GCP Transcoder API (0,005-0,010 $/min)
- **Player**: Vidstack avec hls.js
- **CDN**: directement R2 (egress free) ou Cloudflare devant

Cette stack est ~2-3x moins chère **à très haut volume** (10k+ vidéos/mois) mais demande dette infra non-triviale. Sources: [Lambda FFmpeg cost](https://intoli.com/blog/transcoding-on-aws-lambda/), [R2 vs S3 vs B2 2026](https://leanopstech.com/blog/cloud-storage-pricing-comparison-2026/), [Roll your own HLS](https://yehiaabdelm.com/blog/roll-your-own-hls).

---

## 4. Comparatif coûts: build vs Cloudflare Stream vs Mux vs api.video

Hypothèses: vidéo moyenne 5 min, 1080p, ~50 vues, encodée à ~50 Mo après transcoding.

### 4.1 Pricing 2026 par plateforme (sources officielles)

| Plateforme | Stockage | Encoding | Delivery | Notes |
|---|---|---|---|---|
| **Cloudflare Stream** | 5 $/1k min | gratuit | 1 $/1k min livrée | Inclut HLS, CDN, GIF, storyboard, clipping, signed URLs |
| **Mux Video** | 0,015 $/Go/mois (~équiv ~0,015 $/min) | 0,0075 $/min | 0,15 $/Go (jusqu'à 500 Go), 0,10 $/Go ensuite | Cold storage -60% pour assets non visionnés |
| **api.video** | Pay-as-you-go ou 60 $/mois plan | Encoding gratuit | Bandwidth basé Go | Plan starter 60 $/mois |
| **Bunny Stream** | 0,005 $/Go | 0,02 $/min | 0,005-0,055 $/Go selon zone | Le moins cher à grand volume |
| **Build (R2 + Lambda + CF CDN)** | 0,015 $/Go (~0,75 $/k min) | ~0,001 $/min Lambda | **Gratuit** (R2 egress 0) | Dev infra ~2 j-h/sprint |

Sources: [Cloudflare Stream pricing](https://developers.cloudflare.com/stream/pricing/), [Mux pricing docs](https://www.mux.com/docs/pricing/video), [api.video pricing](https://api.video/pricing/), [Bunny pricing comparison](https://www.pkgpulse.com/blog/mux-vs-cloudflare-stream-vs-bunny-stream-video-cdn-2026), [R2 pricing](https://developers.cloudflare.com/r2/pricing/).

### 4.2 Calculs pour 3 paliers d'usage

**Scénario A — 100 vidéos/mois (early adopters)**
- Volume mensuel: 500 min stockées (5 min × 100), 25 000 min livrées (50 vues × 500 min)
- **Cloudflare Stream**: 0,500 × 5 $ + 25 × 1 $ = **~28 $/mois**
- **Mux**: 5 Go stockés × 0,015 + 1 250 Go livrés × 0,15 = 0,08 + 187 ≈ **~190 $/mois** (delivery dominant)
- **Build**: 5 Go R2 × 0,015 = 0,08 $ + Lambda ~0,5 $ + bandwidth 0 ≈ **~1 $/mois infra** (mais 1-2 sprints pour build l'infra)

**Scénario B — 1 000 vidéos/mois (Showdesk avec ~100 orgs actives)**
- Volume: 5 000 min stockées, 250 000 min livrées (~12 500 Go en HD)
- **Cloudflare Stream**: 5 × 5 + 250 × 1 = **~275 $/mois**, mais avec un Pro plan 25 $ (100 min storage + 10k min delivery free) → ~270 $
- **Mux**: 50 Go × 0,015 + 12 500 Go × ~0,12 ≈ **~1500 $/mois**
- **Build**: 50 Go × 0,015 + Lambda 5-10 $ + bandwidth R2=0 ≈ **~10-15 $/mois infra** + transcription externe

**Scénario C — 10 000 vidéos/mois (gros succès)**
- Volume: 50 000 min stockées, 2,5M min livrées
- **Cloudflare Stream**: 50 × 5 + 2500 × 1 = **~2 750 $/mois**
- **Mux**: 500 Go × 0,015 + 125 000 Go × ~0,10 ≈ **~12 500 $/mois**
- **Build**: 500 Go × 0,015 = ~8 $ stockage + transcoding Lambda ~50-100 $ + R2 egress 0 ≈ **~150 $/mois infra**

### 4.3 Verdict coûts

- **MVP / early stage**: **Cloudflare Stream**. Time-to-market < 1 sprint, prix prévisible, 0 dette infra.
- **Scale (>5 k vidéos/mois)**: réévaluer build interne (R2 + Lambda + custom HLS) — break-even autour de 2-3 k$/mois sur Cloudflare Stream vs ~150 $ infra build (économie réelle: 2 500-2 800 $/mois).
- **Mux**: meilleur DX et analytics, mais delivery cher en Go → seulement si on veut analytics QoE poussées dès le départ. Sa courbe coût explose vs Cloudflare quand le ratio vues/vidéo monte.
- **api.video**: pas dominant techniquement, mais peut convenir si on veut un dashboard fini.

Sources: [BuildMVPFast video costs](https://www.buildmvpfast.com/api-costs/video), [Mux is cheaper than S3](https://www.mux.com/blog/mux-is-cheaper-than-s3) (qui montre que **directement-S3 est plus cher que Mux à mid-scale** — important: l'option naïve "S3+CloudFront" est plus chère que les deux).

---

## 5. Player et expérience de lecture

### 5.1 Choix recommandé: Vidstack

- React-first, hooks (`useMediaState`, `useMediaPlayer`)
- HLS adaptive natif via plugin
- API close de Plyr (migration facile si on a déjà Plyr)
- Permet contrôles custom: vitesse 0.5-2x, captions, chapitres (WebVTT), CTA timecodés
- Bundle size raisonnable (~100 Ko gzipped)
- License Apache 2.0

Source: [Vidstack player](https://vidstack.io/), [GitHub vidstack/player](https://github.com/vidstack/player).

### 5.2 Embed iframe vs natif

- **Iframe** (à la Loom embed): nécessaire pour KB articles externes, emails (la plupart des clients email ne lisent pas video natif → fallback GIF preview animé + lien)
- **Natif** (composant React): dans l'app Showdesk (admin video library, agent inbox)

### 5.3 Watermark / branding

- Cloudflare Stream supporte les **watermark profiles** appliqués à la lecture (logo, position, opacité). Source: [CF Stream API watermarks](https://developers.cloudflare.com/api/resources/stream/subresources/watermarks/).
- Mux: watermark à l'encoding (statique, pas par-user). Pas de watermark forensique sans DRM.
- Pour Showdesk: watermark logo Org en bas-droite (10% opacity) sur les vidéos public/unlisted, désactivable en plan Enterprise.

Sources: [Mux DRM](https://www.mux.com/docs/guides/protect-videos-with-drm), [Gumlet anti-leak](https://www.gumlet.com/learn/anti-leak-private-video-hosting/).

---

## 6. Features avancées — roadmap technique

### 6.1 Transcription auto

- **MVP**: OpenAI gpt-4o-mini-transcribe ($0,003/min = 0,18 $/h) — bon ratio qualité/prix, 50+ langues
- **v2 multilingue / code-switching**: Gladia (100+ langues, fixed per-hour, code-switching natif)
- **Self-hosted fallback**: faster-whisper sur GPU si volume devient gros (>1000 h/mois) — break-even ~150-200 $/mois GPU vs ~180 $ pour 1000 h API

Sources: [Gladia best speech-to-text](https://www.gladia.io/blog/best-speech-to-text-apis), [OpenAI pricing](https://openai.com/api/pricing/), [Whisper vs Google vs AWS](https://vocafuse.com/blog/best-speech-to-text-api-comparison-2025/).

### 6.2 Sous-titres multilingues (traduction auto)

- Source = transcript anglais (ou langue native) → DeepL API ou GPT-4o pour traduction par segment WebVTT
- Coût marginal: ~0,001 $/segment via GPT-4o-mini → négligeable
- Stocker en `.vtt` versionnés par langue, picker dans le player Vidstack

### 6.3 Chapitres auto

- Combinaison Whisper word-timestamps + LLM (GPT-4o-mini) avec prompt: "Découpe ce transcript en 3-7 chapitres avec titre court et timestamp début"
- Ou AssemblyAI Auto Chapters (intégré, mais 0,21 $/h pluri)
- Permettre l'édition manuelle après génération (UX critique)

Sources: [AssemblyAI auto-chapters](https://www.assemblyai.com/blog/automatically-determine-video-sections-with-ai-using-python), [Mux AI chapters](https://www.mux.com/docs/examples/ai-generated-chapters), [Towards Data Science chaptering](https://towardsdatascience.com/automate-video-chaptering-with-llms-and-tf-idf-f6569fd4d32b/).

### 6.4 Trim / cut sans re-upload

**Cloudflare Stream supporte clipping serveur** — on POST `videoUID + start + end` et CF crée un nouvel asset sans re-upload. C'est un game-changer UX. Source: [CF Stream clipping](https://developers.cloudflare.com/stream/edit-videos/video-clipping/).

Mux: pas de clipping natif, il faut télécharger et re-uploader (ou utiliser leur API d'edit limitée).

### 6.5 Thumbnails + GIF preview au survol

- Cloudflare Stream et Mux génèrent automatiquement: thumbnails statiques, animated GIF/WebP, et **storyboard WebVTT** pour scrub-bar hover preview
- Format Mux: `https://image.mux.com/{PLAYBACK_ID}/animated.gif` et `/storyboard.vtt`
- Format CF: `https://customer-{ID}.cloudflarestream.com/{UID}/thumbnails/thumbnail.gif`
- **Email fallback**: animated GIF preview cliquable → page lecteur (Loom utilise ça depuis toujours, c'est THE pattern pour email-to-video)

Sources: [Mux thumbnails & timeline previews](https://www.mux.com/docs/guides/get-images-from-a-video), [Loom GIF preview](https://support.atlassian.com/loom/docs/how-to-create-an-animated-gif-preview/).

### 6.6 Réactions / commentaires timecodés

Pas de magie: stocker des `Comment` avec `timecode_seconds` lié à la `Video`, afficher en overlay player + timeline. Le widget Showdesk a déjà du commentaire (tickets). Modèle simple à étendre.

### 6.7 Analytics (vues, watch time, drop-off)

- **Mux Data**: out-of-the-box (QoE, drop-off, completion). Inclus.
- **Cloudflare Stream**: analytics basiques (vues, durée), pas de drop-off granulaire par défaut → tracker côté player avec Plausible/PostHog
- **Build-it-yourself**: events `video_played`, `video_paused`, `video_seeked` avec timecode → table Postgres `VideoView` + agrégats nightly Celery

Source: [Loom analytics](https://support.atlassian.com/loom/docs/understand-your-videos-views-and-analytics/).

---

## 7. Intégration Showdesk

### 7.1 Modèle de données (extension proposée)

Le modèle actuel `VideoRecording` est lié à `Ticket` (ForeignKey CASCADE). Pour la vidéothèque interne, il faut découpler:

```python
class InternalVideo(TimestampedModel):
    organization = FK(Organization, related_name='videos')
    created_by = FK(User, related_name='created_videos')
    
    # Cloudflare Stream
    cf_stream_uid = CharField(unique=True)
    cf_playback_url = URLField()
    cf_thumbnail_url = URLField()
    cf_gif_url = URLField()
    
    title = CharField(max_length=200)
    description = TextField(blank=True)
    duration_seconds = FloatField()
    
    # Privacy
    visibility = CharField(choices=['private','org','unlisted','public'])
    requires_signed_url = BooleanField(default=True)
    password_hash = CharField(blank=True)  # optionnel
    
    # Linked content
    ticket_replies = M2M(Ticket, through='VideoTicketReply')
    kb_articles = M2M(Article, through='VideoKBEmbed')
    
    # Categorization
    folder = FK('VideoFolder', null=True)
    tags = M2M(Tag)
    
    # AI
    transcript = TextField(blank=True)
    chapters = JSONField(default=list)  # [{start: 0, end: 60, title: "Intro"}]
    captions_languages = ArrayField(CharField())  # ['en', 'fr', 'es']
```

Le `VideoRecording` actuel reste pour les vidéos enduser-side du widget — deux concepts séparés.

### 7.2 Bouton "Enregistrer une vidéo" dans le composer ticket

- Bouton dans la toolbar du `RichTextEditor` du composer reply ticket
- Click → modale avec recorder (réutilise widget recorder logic)
- Stop → upload tus.io en BG + enregistrement immédiat dans la KB Org
- Insertion automatique d'un embed `<showdesk-video uid="..." />` dans le reply
- Email reply: rendu HTML avec GIF preview + lien vers lecteur web

### 7.3 Bibliothèque centrale (Library)

- Page `/admin/videos` listing par Org
- Filtres: créateur, dossier, tags, durée, visibilité
- Search full-text sur transcript (Postgres tsvector sur `transcript`)
- Bulk: change visibility, add tags, move to folder, delete

### 7.4 Embed dans articles KB / portail

- Markdown extension `:::video uid=abc:::` ou shortcode → render `<iframe>` Vidstack
- Articles KB exportés en SEO ont oEmbed metadata → previews riches sur Slack, Twitter, Notion
- Cf existant: KB+Portal sur Showdesk (apps `knowledge_base` déjà présente)

### 7.5 Embed dans email de réponse

- Templating email Showdesk → insère `<a href="..."><img src="{gif_preview}"></a>` en HTML
- Fallback texte: lien direct
- Tracker l'ouverture via pixel (déjà fait pour tickets) + tracker `video_play` quand le user clique

### 7.6 Réutilisation pipeline widget enduser

- Le widget enduser uploade aussi des vidéos (déjà). Dans la stack cible: ces vidéos passent **aussi** par tus → Cloudflare Stream
- Distinction sémantique seulement: `VideoRecording` (enduser, ticket-bound, expirable) vs `InternalVideo` (agent, org-bound, persistant)
- Possibilité de "promote" une vidéo enduser en `InternalVideo` (avec consentement) si elle est utile pour la KB

---

## 8. Privacy / sécurité

### 8.1 Niveaux de visibilité proposés

| Niveau | Description | Implémentation |
|---|---|---|
| **Private** | Seul le créateur | Signed URL JWT lié au user.id, expiration 1h |
| **Organization** | Membres de l'Org | Signed URL JWT lié à org.id, exp 4h, refresh côté player |
| **Unlisted** | Anyone with link, pas indexé | Public playback, `noindex` meta + `disallow` robots |
| **Public** | Listé dans le portail | Playback public, indexable SEO |
| **Password-protected** | Mot de passe pour accéder | Page intermédiaire qui valide → cookie → signed URL court |

### 8.2 Anti-leak

- **Watermark dynamique** par viewer: nom/email du viewer en bas-droite avec opacity. Cloudflare Stream watermark profile + variantes par viewer (génère N variantes, ou superpose côté player JS — moins sécurisé)
- **Signed URLs courte durée** + IP-binding (Cloudflare supporte `accessRules`)
- **Pas de DRM dans le MVP**: complexe, cher, et le cas d'usage Showdesk ne le justifie pas (ce n'est pas du contenu premium type Netflix). DRM seulement si demande client Enterprise.

Sources: [CF Stream signed URLs](https://developers.cloudflare.com/stream/viewing-videos/securing-your-stream/), [Mux signed URLs JWT](https://www.mux.com/articles/securing-video-playback-with-signed-urls), [Loom security](https://support.atlassian.com/loom/docs/use-looms-privacy-settings/), [Loom 2024 vulnerability historique](https://yvoschaap.com/weblog/loom_leaks_private_video_snippet_clips_as_a_feature) — leçon: ne JAMAIS exposer des URLs prédictibles, toujours JWT.

### 8.3 RGPD / rétention

- TTL configurable par Org (90j default pour vidéos endusers, illimité pour InternalVideo sauf opt-in)
- Soft-delete + purge cron Celery → DELETE chez Cloudflare Stream API
- Export: utiliser CF Stream MP4 download endpoint pour permettre takeout

---

## 9. Roadmap

### MVP (Phase 1, ~6 sem)

**Objectif**: un agent peut enregistrer une vidéo dans Showdesk et l'insérer dans un reply ticket.

- [ ] Schéma `InternalVideo` + migrations
- [ ] Recorder UI agent (réutilise `widget/src/recorder/*`)
- [ ] Upload tus.io → Cloudflare Stream (direct-creator-upload pattern)
- [ ] Webhook CF Stream → `InternalVideo.status = ready`
- [ ] Player Vidstack basique dans Showdesk
- [ ] Bouton recorder dans composer reply ticket
- [ ] Email rendering avec GIF preview + lien
- [ ] Library page (list + filter basique)
- [ ] Visibility: private + organization (JWT signed URLs)

### v2 (Phase 2, ~6 sem)

**Objectif**: features Loom-parity pour usage quotidien.

- [ ] Transcription auto (gpt-4o-mini-transcribe)
- [ ] Sous-titres mono-langue + édition manuelle
- [ ] Chapitres auto (LLM) + édition manuelle
- [ ] Trim/cut serveur (CF Stream clipping API)
- [ ] Custom thumbnail (frame picker ou upload)
- [ ] Embed dans articles KB
- [ ] Search full-text dans transcripts (Postgres tsvector)
- [ ] Folders + tags + bulk actions library

### v3 (Phase 3, ~6 sem)

**Objectif**: features avancées et différenciation.

- [ ] Sous-titres multilingues (traduction auto via GPT-4o-mini ou DeepL)
- [ ] Analytics watch-time + drop-off
- [ ] Commentaires/réactions timecodés
- [ ] Watermark dynamique par viewer
- [ ] Password-protected videos
- [ ] CTA timecodés (ex: "Cliquer pour ouvrir le ticket")
- [ ] Vidéos publiques dans portail SEO
- [ ] Extension Chrome (pour record en dehors de Showdesk: ex un dashboard interne client)

### v4 (Phase 4, optionnel)

- [ ] App desktop (Tauri) si demande Safari macOS forte
- [ ] DRM Enterprise (Cloudflare Stream supporte Widevine + FairPlay)
- [ ] Live recording → broadcast (CF Stream Live)
- [ ] AI summary auto (GPT-4o sur transcript)
- [ ] Templates / branded intro-outro auto-stitch (à la Tella)

---

## 10. Risques et mitigations

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| Audio système Safari macOS impossible | **Certain** | Moyen | Documenter; afficher warning détecté par UA; suggérer Chrome ou app desktop v4 |
| Recordings 4K/5K fail (`EncodingError`) | Élevée | Faible | Cap 1440p côté UI + fallback MIME; afficher message si error |
| Vidéos > 30 min en RAM crash | Moyenne | Moyen | Streaming upload chunks 5 s (déjà standard); cap UI 1h |
| Coût bande passante explose si KB devient virale | Faible | **Élevé** | CF Stream pricing en minute (pas Go) → rentable quel que soit le succès. Si build interne: R2 egress = 0, donc safe |
| Loom/Atlassian crée une feature anti-clone (ex. browser extension blocker) | Très faible | Faible | N/A — on n'utilise pas leur infra |
| Transcript leak données sensibles (PII) | Moyenne | Élevé | Détection PII via regex + LLM avant indexation; option "Pas de transcription" par video |
| Latency upload pour gros fichiers en mobile | Moyenne | Moyen | tus.io résumable + upload pendant record (perçu instant) |
| Cloudflare lock-in | Moyenne | Moyen | Sauvegarde MP4 originals dans R2 → migration possible vers self-host ou Mux |
| Coût transcription si gros volume | Faible | Faible | Self-host faster-whisper si > 1000 h/mois |
| GDPR / data residency EU | Moyenne | Moyen | CF Stream a edge EU; mais pour clients enterprise EU strict → option "EU-only storage" (R2 buckets EU) |

---

## Annexe A — Liens techniques utiles

### Recording
- [MDN MediaRecorder](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder)
- [MDN canvas captureStream](https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/captureStream)
- [Mozilla webcam canvas captureStream blog](https://blog.mozilla.org/webrtc/enhancing-webcam-using-capturestream/)
- [WebRTC samples canvas-record](https://webrtc.github.io/samples/src/content/capture/canvas-record/)
- [addpipe getDisplayMedia demo](https://addpipe.com/getdisplaymedia-demo/)
- [Chrome 141 macOS system audio](https://blog.addpipe.com/getdisplaymedia-allows-capturing-the-screen-with-system-sounds-on-chrome-on-macos/)
- [Real-time video processing WebCodecs](https://webrtchacks.com/real-time-video-processing-with-webcodecs-and-streams-processing-pipelines-part-1/)

### Upload
- [tus.io protocol 1.0.x](https://tus.io/protocols/resumable-upload)
- [CF Stream tus uploads](https://developers.cloudflare.com/stream/uploading-videos/resumable-uploads/)
- [Uppy tus](https://uppy.io/docs/tus/)
- [S3 multipart resumable](https://medium.com/@selvakumar.ponnusamy/resumable-file-upload-with-s3-ce039cbc8865)

### Plateformes vidéo
- [Cloudflare Stream pricing](https://developers.cloudflare.com/stream/pricing/)
- [CF Stream clipping](https://developers.cloudflare.com/stream/edit-videos/video-clipping/)
- [CF Stream signed URLs](https://developers.cloudflare.com/stream/viewing-videos/securing-your-stream/)
- [Mux pricing docs](https://www.mux.com/docs/pricing/video)
- [Mux storyboards](https://www.mux.com/blog/tricky-storyboards-and-trick-play)
- [Mux signed URLs JWT](https://www.mux.com/articles/securing-video-playback-with-signed-urls)
- [api.video pricing](https://api.video/pricing/)
- [Bunny Stream comparison](https://www.pkgpulse.com/blog/mux-vs-cloudflare-stream-vs-bunny-stream-video-cdn-2026)
- [Foliovision pricing comparison](https://foliovision.com/player/video-security/encoding/pricing-comparison-cloudflare)
- [BuildMVPFast video API costs](https://www.buildmvpfast.com/api-costs/video)

### Storage
- [Cloudflare R2 pricing](https://developers.cloudflare.com/r2/pricing/)
- [R2 vs S3 vs B2 2026](https://leanopstech.com/blog/cloud-storage-pricing-comparison-2026/)
- [Mux is cheaper than S3](https://www.mux.com/blog/mux-is-cheaper-than-s3)

### Transcoding self-hosted
- [Lambda FFmpeg cost vs Elastic Transcoder](https://intoli.com/blog/transcoding-on-aws-lambda/)
- [Roll your own HLS R2](https://yehiaabdelm.com/blog/roll-your-own-hls)
- [GCP Transcoder API pricing](https://cloud.google.com/transcoder/pricing)

### Player
- [Vidstack player](https://vidstack.io/)
- [Vidstack React install](https://vidstack.io/docs/player/getting-started/installation/react/)
- [Best React video libs Croct 2026](https://blog.croct.com/post/best-react-video-libraries)

### Transcription
- [OpenAI API pricing](https://openai.com/api/pricing/)
- [Gladia vs AssemblyAI vs Deepgram](https://www.gladia.io/blog/best-speech-to-text-apis)
- [Whisper API pricing per minute 2026](https://tokenmix.ai/blog/whisper-api-pricing)

### Concurrents
- [Loom pricing 2026](https://www.atlassian.com/software/loom/pricing)
- [Loom Atlassian post-acquisition](https://supademo.com/blog/loom-pricing)
- [Tella vs Loom](https://www.albertodirisio.com/tella-vs-loom/)
- [Vidyard vs Loom Arcade](https://www.arcade.software/post/vidyard-vs-loom)
- [Cap GitHub OSS](https://github.com/CapSoftware/Cap)
- [Loom GIF previews](https://support.atlassian.com/loom/docs/how-to-create-an-animated-gif-preview/)
- [Loom analytics](https://support.atlassian.com/loom/docs/understand-your-videos-views-and-analytics/)
- [Loom security & privacy](https://support.atlassian.com/loom/docs/use-looms-privacy-settings/)

### Codecs
- [MDN Web video codec guide](https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Formats/Video_codecs)
- [Uploadcare codec landscape 2025](https://uploadcare.com/blog/navigating-codec-landscapes/)
- [AV1 vs VP9 vs VP8 comparison](https://www.red5.net/blog/av1-vs-vp9-vs-vp8-comparison-for-live-streaming/)
