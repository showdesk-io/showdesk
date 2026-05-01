# Portail Help Desk public/semi-public par Organization

> Brainstorm — 2026-05-01
> Auteur : recherche agent + d.refauvelet@sparkup.app
> Statut : exploratoire, à valider avant chiffrage MVP.

---

## TL;DR

- **But** : doter chaque Organization Showdesk d'une **page help desk publique** (URL type `help.acme.com` ou `acme.showdesk.io`) qui agrège : KB / centre d'aide, vidéothèque tutoriels, status page, formulaire ticket, et — pour l'enduser authentifié — l'historique de ses tickets.
- **Positionnement marché** : c'est le **chaînon manquant** entre le widget Showdesk (capture + ticket) et un vrai produit support. Sans portail, on reste un "feedback widget" ; avec, on devient une alternative Crisp / Zendesk Suite pour startups SaaS.
- **Architecture recommandée** : Next.js (SSR pour SEO) ou un sous-app React Vite servie par Django via slug d'organisation. URL pattern : `{slug}.showdesk.io` par défaut, custom domain `help.acme.com` via **Caddy on-demand TLS** (gratuit, illimité) en MVP, **Cloudflare for SaaS** ($0,10/domaine/mois) si on dépasse ~5k clients.
- **Auth enduser** : 3 modes — anonyme (lecture KB), **magic link email** (voir ses tickets), **session widget** (déjà existante via `X-Widget-Session`). SSO SAML/OIDC en v3 (entreprise).
- **KB** : modèle `Article` actuel à enrichir (locale, tags, version, search_vector, SEO meta). Editeur **TipTap** (le plus mature React, ProseMirror sous le capot). Recherche : **Postgres FTS + pg_trgm** en MVP, **Meilisearch** si besoin de typo tolerance et search-as-you-type.
- **Status page** : **build interne** light (composants + incidents + maintenances + abonnements email), pas d'intégration externe en MVP. C'est ~1 semaine de dev, et ça renforce le positionnement "all-in-one".
- **Vidéothèque** : **réutiliser le pipeline `videos` existant** (VideoRecording, déjà en place) — un article KB peut référencer plusieurs vidéos Showdesk et/ou des embeds Loom/YouTube.
- **MVP réaliste** : ~3 à 4 semaines de dev pour KB publique + portail tickets + sous-domaine `{slug}.showdesk.io`. Status page et custom domain en v2.

---

## 1. Comparatif concurrents

### 1.1 Vue d'ensemble (2026)

| Outil | Cible | URL portail | Custom domain | KB inclus | Status page | Pricing/mois | Note |
|---|---|---|---|---|---|---|---|
| **Zendesk Guide** | Mid-market / enterprise | `{org}.zendesk.com/hc` | Oui (host mapping + Let's Encrypt gratuit) | Oui, riche, multi-langue, multi-brand | Non (Atlassian Statuspage séparé) | $55–249/agent (Suite) | Le plus abouti, le plus cher |
| **Intercom Help Center** | SaaS scale-ups | `{org}.intercom.help` | Oui (CNAME + SSL flexible Cloudflare) | Articles Fin AI deflection 60% | Non | $74/seat (Essential) | Bon en chat + AI, KB plus simple |
| **Freshdesk** | SMB/SME | `{org}.freshdesk.com` | Oui | Oui, basique | Non | $15/agent (Growth), free 10 agents | Très accessible, free tier généreux |
| **HelpScout Docs** | SMB support | `{org}.helpscoutdocs.com` | Oui | Oui + Beacon widget intégrable | Non | $25/user (Standard) | Simple, KB-first |
| **Crisp Helpdesk** | Startups | `acme.crisp.help` ou `help.acme.com` | Oui (sub) | Oui (Essentials 95€) | Non | 95–295€/workspace | All-in-one chat+KB, modèle workspace (pas par agent) |
| **Plain.com** | B2B dev tools (Vercel, Cursor) | `support.site` ou custom | Oui | Headless ou hosted | Non | API-first, sur devis | Le plus moderne, B2B engineering-led |
| **Pylon** | B2B Slack-first | Help center hosté | Oui | AI-natif, knowledge gap detection | Non | $59/user/mois | Concurrent direct si on vise B2B |
| **Document360** | Enterprise KB | `docs.{org}.com` | Oui | Enterprise KB pure (pas ticketing) | Non | $99–499/mois flat | KB-only, pas helpdesk |
| **Helpjuice** | Enterprise KB | Custom | Oui | AI search + 40+ langues auto-traduites | Non | $120–499/mois flat | KB-only, focus translation |
| **GitBook** | Dev tools / API docs | `*.gitbook.io` | Oui | Git-based, API ref-friendly | Non | $8–12.5/user | Pour docs dev, pas helpdesk |
| **Notion** | Internal wikis | Notion-published page | Limité | Non (juste pages) | Non | $10/user | Trop bricolé pour help center sérieux |
| **Statuspage.io** | Status only | `{org}.statuspage.io` | Oui | Non | Oui (référence) | $29–399/mois | Seul status, pas KB |
| **Instatus** | Status, indie | `{org}.instatus.com` | Oui | Non | Oui (rapide, joli) | $20–300/mois | 10× plus rapide que Statuspage.io |
| **Better Stack** | Monitoring + status | Custom | Oui | Non | Oui (intégré au monitoring) | $12–29/mois start | Combine uptime + status |
| **Cachet** | Open source | Self-hosted | Oui | Non | Oui (self-host) | Free | v2 abandonné, v3 en chantier (Vue+Laravel), pas prod-ready |

Sources principales : [eesel AI Zendesk pricing](https://www.eesel.ai/blog/zendesk-plans-and-pricing), [eesel AI Pylon review 2026](https://www.eesel.ai/blog/pylon), [Plain.com produit](https://www.plain.com/product), [Crisp pricing 2026](https://help.crisp.chat/en/article/setup-your-knowledge-base-domain-name-1fkjw73/), [Hyperping Statuspage alternatives 2026](https://hyperping.com/blog/best-statuspage-alternatives), [Better Stack open-source status page tools](https://betterstack.com/community/comparisons/free-status-page-tools/).

### 1.2 Patterns récurrents

1. **URL = sous-domaine par défaut + custom domain optionnel.**
   Tous offrent `{slug}.outil.com` gratuitement, et `help.client.com` via CNAME + SSL géré (Let's Encrypt). C'est devenu un standard, pas un différenciateur.
2. **KB = catégories → articles, statut draft/published, multi-langue.**
   Tous ont catégories, articles, états (draft/published/archived), souvent versioning. Multi-langue via "translations" liées à un article maître.
3. **Search**: tous ont une barre de recherche full-text. Pylon et Helpjuice ajoutent AI search (RAG sur le KB).
4. **Deflection AI** (Intercom Fin, Pylon, Zendesk AI agents) : avant un ticket, suggérer 3–5 articles ; mesurer le taux de "résolu sans humain" (Fin atteint 60%+ selon [Intercom](https://www.intercom.com/help/en/articles/8205718-fin-ai-agent-outcomes)).
5. **Theming** : tous limités à logo + couleurs + fonts ; quelques-uns (Zendesk Guide, Crisp Plus) autorisent CSS/HTML custom — au prix d'une support cassé sur les nouvelles features (cf. [Zendesk theming](https://support.zendesk.com/hc/en-us/articles/4408821255834-About-the-standard-theme-and-custom-themes-in-your-help-center)).
6. **Status page séparée** : aucun ne bundle status page dans le helpdesk. C'est *l'opportunité Showdesk*. Atlassian a Statuspage en SKU séparé, ce qui force à payer 2 outils ($299–499/mois cumulé).

### 1.3 Notes sur les concurrents directs

- **Crisp Helpdesk** est le plus proche de Showdesk côté positionnement (workspace flat, all-in-one). Il a KB + custom domain + email custom à 95€/mois Essentials. Mais : pas de video recording natif, pas de status page, hosting US.
- **Plain** est la référence "dev-first / B2B SaaS" — leur portail est *headless* (l'agence intègre comme elle veut). Showdesk peut s'inspirer de leur posture API-first sans aller jusqu'au headless pur (trop technique pour startups <20 agents).
- **Pylon** (Slack-first) est une bonne référence pour le côté "AI-native KB" — détection de gaps de connaissance, suggestion d'articles à écrire, traduction auto. Bon north star v3.

---

## 2. Architecture proposée

### 2.1 URL strategy

```
Default:        acme.showdesk.io               <- inclus, gratuit
Custom domain:  help.acme.com                  <- option, via CNAME
Sous-pages:     /                              <- landing portail
                /kb                            <- knowledge base
                /kb/{category-slug}            <- categorie
                /kb/{category-slug}/{article}  <- article (SEO)
                /tickets                       <- portal tickets (auth requis)
                /tickets/{reference}           <- detail ticket
                /status                        <- status page publique
                /videos                        <- videotheque
                /search?q=...                  <- recherche unifiee
                /new                           <- ouvrir un nouveau ticket
```

**Rationale URL** :
- `kb/category/article` plutôt que `articles/article` pour une meilleure hiérarchie SEO (cf. [Zendesk Guide SEO critique](https://asadzulfahri.com/blog/4-reasons-why-zendesk-help-center-is-bad-for-seo/) où Zendesk impose `/hc/en-us/articles/{id}-{slug}` pénalisant).
- `/status` séparé de `/kb` pour permettre un cache CDN agressif sur status (qui doit toujours répondre, même si le backend est down).

### 2.2 Routing technique

#### Option A — Sous-app React intégrée (recommandée MVP)

```
Caddy
 ├── api.showdesk.io       -> Django (DRF + Channels)
 ├── app.showdesk.io       -> React (interface agent, JWT)
 ├── *.showdesk.io         -> React portal (slug-based)
 │     - middleware: detecte sous-domaine, fetch /api/v1/public/orgs/by-slug/{slug}
 │     - rendu portail isole (theme, brand, locale)
 └── (custom domains)      -> resolve via on-demand TLS, header Host injecte
```

#### Option B — Next.js dédié au portail (recommandée v2)

Si on veut un SEO musclé et SSR/ISR, séparer le portail dans une app **Next.js 15** avec :
- `app/[locale]/kb/[category]/[slug]/page.tsx` (ISR 60s)
- `app/[locale]/status/page.tsx` (revalidate 10s)
- Fetch via API REST Django, pas direct DB
- Déployable sur Vercel ou self-host derrière Caddy

**Décision** : commencer en **option A** (React Vite déjà en place, time-to-MVP < 2 semaines), migrer vers option B uniquement quand le SEO devient un levier d'acquisition mesuré (>10k visits/mois sur KB).

### 2.3 Custom domain + SSL

#### Solution recommandée MVP : **Caddy on-demand TLS**

- Déjà en place (Caddy système devant Docker).
- Configurer `on_demand_tls` avec un endpoint `ask` qui valide que le domaine demandé existe dans `Organization.custom_domain`.
- Coût : **0 €**. Limite : 50 nouveaux certs/semaine par registered domain (limite Let's Encrypt, mais chaque custom domain a son propre registered domain → effectivement illimité). Voir [Caddy automatic HTTPS docs](https://caddyserver.com/docs/automatic-https) et [Caddy on-demand TLS guide](https://fivenines.io/blog/caddy-tls-on-demand-complete-guide-to-dynamic-https-with-lets-encrypt/).
- Onboarding client : "ajoutez un CNAME `help.acme.com → cname.showdesk.io`, on s'occupe du SSL".

```caddyfile
{
  on_demand_tls {
    ask https://api.showdesk.io/api/v1/internal/domain-allowed/
    rate_limit 10 1m
  }
}

https:// {
  tls {
    on_demand
  }
  reverse_proxy frontend:80
}
```

#### Solution v2/scale : **Cloudflare for SaaS**

Si on dépasse ~5k clients ou qu'on veut WAF + DDoS + CDN edge sur les portails clients :
- $0,10/custom hostname/mois après les 100 premiers gratuits ([Cloudflare for SaaS plans](https://developers.cloudflare.com/cloudflare-for-platforms/cloudflare-for-saas/plans/)).
- Limite 50k domains/account ([LowEndTalk discussion](https://lowendtalk.com/discussion/213319/alternative-to-cloudflare-for-saas-for-more-than-50k-custom-domains)).
- API simple : `POST /custom_hostnames` avec le domaine du client, Cloudflare valide et émet un cert auto.
- Bonus : edge cache → KB ultra rapide partout.

Pour 1000 clients custom domain : ~90$/mois — négligeable face au revenu généré.

#### Solution premium : **bring your own cert**

Pour entreprises qui veulent un EV cert : permettre l'upload d'un cert PEM via UI agent. Optionnel.

### 2.4 Hosting / infra

- **Cache statique** : KB et status doivent être **fortement cachés** (Cache-Control `s-maxage=60, stale-while-revalidate=600`). Invalidation côté Django via signal `post_save` sur Article/Incident → purge endpoint Caddy/Cloudflare.
- **CDN images** : déjà MinIO/S3 → préfixer `cdn.showdesk.io` pour servir public.
- **Status page priorité** : doit fonctionner même quand Django est down. Option : Status snapshot statique régénéré toutes les 10s par Celery, écrit en `S3://status/{org-slug}.json`, lu directement par CDN. Robuste.

---

## 3. Modèle de données KB (proposition)

Le modèle actuel (`apps/knowledge_base/models.py`) est minimal : `Category` + `Article` plat, pas de locale, pas de tags, pas de version. À enrichir :

### 3.1 Schéma proposé

```python
# apps/knowledge_base/models.py (proposed)

class Locale(models.Model):
    """Liste des locales actives pour le portail (en, fr, es...)."""
    code = models.CharField(max_length=10, unique=True)  # 'en', 'fr', 'fr-FR'
    name = models.CharField(max_length=50)
    is_default = models.BooleanField(default=False)


class Category(TimestampedModel):
    organization = models.ForeignKey(...)
    parent = models.ForeignKey('self', null=True, blank=True, related_name='children')
    slug = models.SlugField(max_length=255)
    icon = models.CharField(max_length=50, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=False)


class CategoryTranslation(models.Model):
    category = models.ForeignKey(Category, related_name='translations')
    locale = models.ForeignKey(Locale)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    class Meta:
        unique_together = [('category', 'locale')]


class Article(TimestampedModel):
    organization = models.ForeignKey(...)
    category = models.ForeignKey(Category, ...)
    slug = models.SlugField(max_length=500)
    status = models.CharField(choices=DRAFT/PUBLISHED/ARCHIVED, ...)
    author = models.ForeignKey(User, ...)
    published_at = models.DateTimeField(null=True, blank=True)

    # SEO
    seo_title = models.CharField(max_length=255, blank=True)
    seo_description = models.TextField(blank=True)
    og_image = models.ImageField(...)

    # Metrics
    view_count = models.PositiveIntegerField(default=0)
    helpful_count = models.PositiveIntegerField(default=0)
    not_helpful_count = models.PositiveIntegerField(default=0)
    deflection_count = models.PositiveIntegerField(default=0)  # 'a evite un ticket'

    # Tags pour suggestion / IA
    tags = models.ManyToManyField('Tag', blank=True)


class ArticleTranslation(models.Model):
    article = models.ForeignKey(Article, related_name='translations')
    locale = models.ForeignKey(Locale)
    title = models.CharField(max_length=500)
    body = models.JSONField()  # TipTap JSON output, pas du HTML
    body_text = models.TextField()  # version plain text pour FTS
    search_vector = SearchVectorField(null=True)  # GIN-indexed Postgres FTS
    is_machine_translated = models.BooleanField(default=False)
    last_human_edited_at = models.DateTimeField(null=True)

    class Meta:
        unique_together = [('article', 'locale')]
        indexes = [GinIndex(fields=['search_vector'])]


class ArticleVersion(models.Model):
    """Historique des versions d'un article (revert, audit)."""
    article = models.ForeignKey(Article)
    locale = models.ForeignKey(Locale)
    body = models.JSONField()
    saved_by = models.ForeignKey(User)
    created_at = models.DateTimeField(auto_now_add=True)


class ArticleVideo(models.Model):
    """Lien article -> VideoRecording (reuse du modele videos existant)."""
    article = models.ForeignKey(Article)
    video = models.ForeignKey('videos.VideoRecording')
    sort_order = models.PositiveIntegerField(default=0)


class Tag(TimestampedModel):
    organization = models.ForeignKey(...)
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=80)
```

### 3.2 Choix de stockage du contenu

**Recommandation** : **JSON TipTap** (ProseMirror schema) plutôt que HTML brut.

- Avantages : extraction facile pour search (`body_text`), ré-export en HTML/Markdown/PDF, embedding (`embed-iframe`, `video-showdesk`, `youtube`, etc.) bien typé, pas d'XSS si on whitelist les nodes.
- Cf. [TipTap vs Lexical 2026](https://trybuildpilot.com/609-tiptap-vs-lexical-vs-plate-editor-2026) : TipTap est le choix par défaut React 19, écosystème de 50+ extensions officielles, intègre bien Y.js pour collaboratif (futur).

### 3.3 SEO

- **Sitemap** : Django génère `sitemap.xml` par org, inclut `<xhtml:link rel="alternate" hreflang>` pour multi-langue ([guide hreflang 2026](https://www.digitalapplied.com/blog/international-seo-2026-hreflang-multilingual-guide)).
- **OG / Twitter cards** : champs `seo_*` + `og_image` sur `Article`.
- **schema.org/FAQPage** ou `Article` JSON-LD injecté dans `<head>` du portail.
- **Canonical** : article maître = locale par défaut, traductions = self-canonical + hreflang croisé.
- **Robots.txt** par org, généré dynamiquement.

---

## 4. Authentification enduser sur le portail

### 4.1 Trois modes (par ordre d'implémentation)

#### Mode 1 — Anonyme (lecture seule KB) — **MVP**
- Aucune auth pour `/kb/*`, `/status`, `/videos`.
- Cache CDN agressif.
- Tracking analytics opt-in (cookie consent EU/RGPD).

#### Mode 2 — Magic link email (voir ses tickets) — **MVP**
- Sur `/tickets`, l'enduser entre son email → reçoit un magic link `/tickets/auth?token=...`.
- Token JWT court (15 min) + refresh JWT long (7 jours, HttpOnly cookie).
- Réutiliser le système OTP existant (`OTPCode` dans `apps/organizations/models.py`) en mode "magic link" : on envoie le lien `/?token={otp.code}` au lieu d'afficher le code.
- Sécurité : token mono-usage, lié à l'email, sécurisé HMAC contre l'org.
- UX : "Welcome back, john@acme.com — 3 active tickets".
- Voir [Stytch B2B magic link auth](https://stytch.com/docs/b2b/api/authenticate-magic-link), [Auth0 passwordless](https://auth0.com/docs/authenticate/passwordless/authentication-methods/email-magic-link).

#### Mode 2bis — Session widget partagée — **MVP**
- Si l'enduser arrive depuis le widget (header `X-Widget-Session` présent dans localStorage), on autorise l'accès au portail aux tickets liés à `widget_session_id`.
- Permet une transition fluide widget → portail sans re-login.
- Limite : session = device (lost on browser change). Magic link recommandé pour persistance.

#### Mode 3 — SSO entreprise (SAML/OIDC) — **v3**
- Pour clients enterprise dont les endusers sont des employés (ex: portail interne). 
- Voir [Customer portal authentication options](https://www.supportbench.com/customer-portal-authentication-sso-magic-links-invite-only-access/), [WorkOS](https://workos.com/) pour intégration OIDC/SAML clé en main.
- Pas de demande client réelle aujourd'hui → reporter.

### 4.2 Liaison avec le widget existant

L'identification HMAC widget (`external_user_id` + `user_hash` via `widget_secret`, cf. `Organization.verify_user_hash`) doit être **réutilisable** côté portail :

```
widget HMAC auth -> WidgetSession.linked_user (existing)
                 -> portail JWT cookie
```

Si l'app cliente a déjà un user identifié côté SaaS, elle peut générer un lien direct vers le portail :
`https://help.acme.com/sso?user_id=ext-123&hash=hmac(widget_secret, 'ext-123')`

→ même contrat HMAC que le widget. Zéro friction pour l'enduser.

### 4.3 Recap matrice auth

| Action | Anonyme | Widget session | Magic link | SSO |
|---|---|---|---|---|
| Lire KB | OK | OK | OK | OK |
| Lire articles privés | NON | NON | OK (si autorisé) | OK |
| Voir mes tickets | NON | OK (session locale) | OK (cross-device) | OK |
| Ouvrir ticket | OK (anon) | OK | OK | OK |
| Voter helpful | OK | OK | OK | OK |
| Status page | OK | OK | OK | OK |
| S'abonner aux incidents | OK (par email) | OK | OK | OK |

---

## 5. Status page : build vs intégrer

### 5.1 Recommandation : **build interne, light**

**Pourquoi build :**
1. **Positionnement all-in-one** : Showdesk = "le widget + le portail + le statut, tout en un". Sans status page native, on force le client à ajouter Atlassian Statuspage ($29/mois) ou Instatus ($20/mois) → casse le pitch.
2. **Coût dev faible** : ~5–7 jours dev (modèles + UI public + UI agent + abonnements email). Cf. modèle minimaliste de [Cachet](https://github.com/cachethq/cachet) qu'on peut s'inspirer.
3. **Données déjà en main** : Showdesk a déjà notifications + Channels + Celery. Push d'un incident = 50 lignes.
4. **Cachet n'est pas une option ready-to-use** : v2 abandonné depuis 2023, v3 en chantier (Vue+Laravel) — pas prod-ready (cf. [Better Stack open-source status tools 2026](https://betterstack.com/community/comparisons/free-status-page-tools/)).

**Pourquoi pas build (à reconsidérer) :**
- Si on veut du monitoring actif (uptime checks depuis 5 régions du monde → SaaS comme Better Stack à $29/mois sont meilleurs sur ce point).
- Si l'utilisateur veut des statuspages multiples par produit (multi-component complex).

### 5.2 Modèle proposé

```python
# apps/status/models.py (new app)

class Component(TimestampedModel):
    """Service ou composant (API, dashboard, widget...)."""
    organization = models.ForeignKey(...)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    current_status = models.CharField(
        choices=[
            ('operational', 'Operational'),
            ('degraded', 'Degraded performance'),
            ('partial_outage', 'Partial outage'),
            ('major_outage', 'Major outage'),
            ('maintenance', 'Under maintenance'),
        ],
        default='operational',
    )


class Incident(TimestampedModel):
    organization = models.ForeignKey(...)
    title = models.CharField(max_length=255)
    severity = models.CharField(choices=...)  # minor/major/critical
    status = models.CharField(choices=['investigating', 'identified', 'monitoring', 'resolved'])
    started_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    components = models.ManyToManyField(Component)
    is_public = models.BooleanField(default=True)


class IncidentUpdate(TimestampedModel):
    incident = models.ForeignKey(Incident, related_name='updates')
    body = models.TextField()
    status = models.CharField(choices=...)
    posted_by = models.ForeignKey(User, null=True)


class Maintenance(TimestampedModel):
    organization = models.ForeignKey(...)
    title = models.CharField(max_length=255)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    components = models.ManyToManyField(Component)


class StatusSubscription(TimestampedModel):
    organization = models.ForeignKey(...)
    email = models.EmailField()
    components = models.ManyToManyField(Component, blank=True)
    confirmed = models.BooleanField(default=False)
    unsubscribe_token = models.UUIDField(default=uuid.uuid4)
```

### 5.3 Webhooks d'ingestion

Pour intégrer un monitoring externe (UptimeRobot, Better Stack, Sentry) :
```
POST /api/v1/orgs/{api_token}/incidents/webhook
{
  "title": "API latency spike",
  "severity": "minor",
  "components": ["api"],
  "source": "betterstack"
}
```

→ permet à Showdesk de devenir une "status page agnostique" dont la donnée vient d'où on veut.

---

## 6. Vidéothèque tutorielle

**Réutiliser `apps/videos.VideoRecording`** : déjà construit pour les tickets (pipeline Celery, expiration, transcription).

Ajouts :
- Type `kind = 'tutorial'` (vs `kind = 'ticket'`) avec `is_public = True`.
- Section `/videos` du portail liste les tutorials publiés, par catégorie KB.
- Article KB peut embed `[video-showdesk:uuid]` qui rend un lecteur Showdesk natif (existant dans frontend agent).
- Embed externe whitelist : `youtube.com`, `loom.com`, `vimeo.com`, `wistia.com`. Cf. [Loom embed SDK](https://dev.loom.com/docs/embed-sdk/getting-started), [Crisp KB Loom embed](https://help.crisp.chat/en/article/how-can-i-embed-videos-from-loom-in-a-helpdesk-article-1vtsmvt/).

Différenciateur Showdesk : **"Record a tutorial in 1 click"** depuis l'admin du portail — réutilise le widget recording (camera + screen + mic) déjà construit. Aucun concurrent ne fait ça (Loom est externe, Wistia est externe).

---

## 7. Recherche unifiée

### 7.1 Recommandation : **Postgres FTS + pg_trgm en MVP, Meilisearch en v2**

**MVP (Postgres FTS + pg_trgm)** :
- Coût : 0 € (déjà dans la stack).
- Indexer : `ArticleTranslation.body_text`, `Article.title`, `Tag.name`, `Ticket.subject` + `TicketMessage.body` (pour la recherche dans son propre historique).
- `SearchVector` Django + `GinIndex` (cf. [Django Postgres FTS docs](https://docs.djangoproject.com/en/6.0/ref/contrib/postgres/search/)).
- `pg_trgm` pour typo tolerance basique ([George London Postgres trigrams](https://www.gjlondon.com/uncategorized/postgres-fuzzy-search-using-trigrams-django/)).
- Limite : performance dégrade au-delà de quelques 10k articles, pas d'instant search <50ms p99.

**v2 (Meilisearch self-host)** :
- Si KB > 5k articles ou demande "search-as-you-type" instantané (UX moderne).
- Coût : ~$15/mois VPS dédié, container Docker à côté de Postgres.
- Multi-tenant via tenant tokens (filtre `organization_id` injecté au search) — cf. [Meilisearch comparison Algolia](https://www.meilisearch.com/blog/algolia-vs-typesense).
- Sync via Celery task on `Article.save()`.

**Algolia** : reject. $1/1000 searches → 1M recherches/mois = $500. Trop cher pour notre pricing $0–49/workspace.

### 7.2 AI deflection (suggestion d'article avant ouverture ticket) — **v2/v3**

Sur `/new` (ouvrir un ticket), pendant que l'enduser tape :
1. Embedder titre+body (OpenAI `text-embedding-3-small`, $0.02/M tokens).
2. Cosine similarity contre embeddings d'articles publiés de l'org.
3. Top 3 articles affichés en sidebar : "Cet article peut-être ?".
4. Si user clique "Cet article répond à ma question" → ticket non créé, `Article.deflection_count += 1`.

**Métriques à tracker** (cf. [Intercom AI metrics](https://www.intercom.com/blog/customer-service-metrics-ai/)) :
- **Deflection rate** = `deflected / (deflected + tickets_created)`. Target : 30%+ MVP, 60%+ avec Fin-like AI.
- **Article view → no ticket within 24h** = "deflexion implicite".
- **Helpful vote rate** par article.
- **Search-no-result** queries (signal de gap KB à combler).

---

## 8. Branding / theming

### 8.1 Niveau MVP (et probablement permanent)

Limiter à un set fini de variables :
- Logo (image)
- Couleur primaire (hex)
- Couleur d'accent (hex)
- Font (Google Fonts whitelist : Inter, Roboto, Open Sans, Montserrat, Lora)
- Hero illustration / image header (optionnel)
- Texte d'accueil (markdown court)
- Lien footer ("Powered by Showdesk" toggleable selon plan)

Toutes ces variables → CSS custom properties injectées au runtime :
```css
:root {
  --portal-primary: #6366F1;
  --portal-accent: #14B8A6;
  --portal-font: 'Inter', sans-serif;
}
```

### 8.2 Pas de CSS custom utilisateur

**Décision** : ne PAS proposer de CSS/HTML custom (contrairement à Zendesk Guide). Raisons :
- Support cassé sur les nouvelles features (Zendesk a ce problème, [docs](https://support.zendesk.com/hc/en-us/articles/4408821255834)).
- Risque XSS / leaks cross-tenant.
- Notre cible (startups SaaS, équipes <20 agents) ne veut pas hacker du HTML.
- Les concurrents qui le permettent (Zendesk, Crisp Plus) sont sur des plans entreprise — pas notre cible.

### 8.3 Layout templates

Proposer 2–3 layouts pré-built :
- **Cards grid** (style Intercom) : catégories en cartes 3-col.
- **List minimal** (style Plain) : liste verticale, gros titres.
- **Hero search** (style Stripe Docs) : grand search bar centré.

---

## 9. Multi-langue (i18n)

### 9.1 Scope

- **UI portail** : i18n via `react-i18next`, fichiers `en.json`, `fr.json`, `es.json`. Maintenu côté Showdesk, pas customisable client (sauf plan enterprise).
- **Contenu KB** : par organisation, opt-in par locale. Article a une "locale par défaut" + N traductions.
- **Status page** : i18n UI, mais incidents toujours dans la langue de l'agent qui les écrit (acceptable).

### 9.2 Détection locale enduser

Order of resolution :
1. Path `/{locale}/...` si présent.
2. Cookie `portal_locale`.
3. Header `Accept-Language`.
4. Locale par défaut de l'org.

URL pattern : `/fr/kb/...` plutôt que `?lang=fr` (meilleur SEO, hreflang).

### 9.3 Auto-translation

- **MVP** : pas d'auto-trad. L'agent traduit manuellement.
- **v2** : bouton "Translate to fr/es/de..." dans l'éditeur d'article → call OpenAI `gpt-4o-mini` ou DeepL API ($0,02/1k chars). Article créé en `is_machine_translated=True`, badge "auto-traduit, à valider" côté agent.
- **v3** : équivalent Helpjuice (40+ langues, auto à la création) — cf. [eesel Document360 vs Helpjuice](https://www.eesel.ai/blog/document360-vs-helpjuice).

### 9.4 hreflang & SEO

- Sitemap par locale : `sitemap-en.xml`, `sitemap-fr.xml`, indexé via `sitemap-index.xml`.
- `<link rel="alternate" hreflang="fr" href="..."/>` dans `<head>` + dans sitemap (cf. [hreflang guide 2026](https://www.digitalapplied.com/blog/international-seo-2026-hreflang-multilingual-guide)).
- Code locale ISO 639-1 + 3166-1 (`fr-FR`, `en-US`).

---

## 10. Priorisation MVP → v2 → v3

### MVP (3–4 semaines de dev)

**Goal** : un portail public minimal qui rend Showdesk crédible face à Crisp.

- [ ] Sous-domaine `{slug}.showdesk.io` (DNS wildcard + Caddy routing).
- [ ] Modèle `ArticleTranslation`, `Locale`, enrichissement `Article` (SEO meta, view_count).
- [ ] Editeur TipTap dans l'admin agent (replace TextField actuel).
- [ ] Pages publiques : `/`, `/kb`, `/kb/{cat}/{slug}`, `/new`, `/tickets`, `/tickets/{ref}`.
- [ ] Recherche Postgres FTS sur articles (org-scoped).
- [ ] Auth magic link enduser (réuse `OTPCode`).
- [ ] Auth via session widget (continuité).
- [ ] Theming : logo + couleur primaire + greeting.
- [ ] Sitemap + robots.txt par org.
- [ ] Page `/status` avec un seul "all systems operational" hardcodé (placeholder).

### v2 (4–6 semaines après MVP)

**Goal** : différencier vs Zendesk/Intercom avec status page native + custom domain + i18n.

- [ ] Status page complète (Component, Incident, Maintenance, Subscription email).
- [ ] Custom domain via Caddy on-demand TLS + UI agent.
- [ ] i18n UI portail (en + fr).
- [ ] i18n contenu KB (Article translations + locale routing).
- [ ] Vidéothèque `/videos` (réuse `videos.VideoRecording` avec `kind=tutorial`).
- [ ] Embed Loom/YouTube whitelist dans TipTap.
- [ ] OG images dynamiques par article (Vercel OG-style).
- [ ] Article versioning + revert.
- [ ] Tags + filtres KB.

### v3 (post-PMF, 8+ semaines)

**Goal** : enterprise-ready + AI native.

- [ ] Cloudflare for SaaS si >5k clients custom domain.
- [ ] SSO SAML/OIDC pour endusers.
- [ ] Auto-translation IA (DeepL ou GPT-4o-mini).
- [ ] AI deflection dans `/new` (embeddings + suggestion).
- [ ] Multi-help-center (par brand de la même org, comme Intercom).
- [ ] Theme avancé (CSS variables étendu, layout templates).
- [ ] Webhooks d'ingestion incidents (Better Stack, Sentry, UptimeRobot).
- [ ] AI knowledge gap detection (à la Pylon : queries sans réponse → suggérer un article à écrire).
- [ ] Migration vers Next.js (SSR/ISR) si SEO devient un levier d'acquisition mesuré.
- [ ] Meilisearch si KB > 5k articles.

---

## 11. Risques

### 11.1 SEO

- **Cannibalisation** entre versions traduites mal hreflang-ées (cf. [étude 75% des sites internationaux ont des erreurs hreflang](https://www.digitalapplied.com/blog/international-seo-2026-hreflang-multilingual-guide)). → tests automatisés sur la sortie sitemap + audit Search Console mensuel.
- **Sous-domaine `*.showdesk.io` vs custom domain** : sous-domaine partage l'autorité de showdesk.io (avantage cold start), mais transfert d'autorité vers le custom domain est coûteux. **Mitigation** : 301 permanent quand un client active son custom domain, et conserver les URLs canonical jusqu'à propagation.
- **Risque "Zendesk SEO problem"** ([asadzulfahri.com](https://asadzulfahri.com/blog/4-reasons-why-zendesk-help-center-is-bad-for-seo/)) : URLs `/hc/en-us/articles/{id}-{slug}` trop profondes, contenu thin, absence H1. Notre design (URLs plates, hreflang propre, SSR/ISR en v2) doit éviter ça by design.

### 11.2 Performance

- **Cold start sur le portail**  : si on rend tout côté Django, premier hit peut être 500ms+. Mitigation : cache Caddy 60s + Cache-Control + S3 static fallback pour status.
- **Long-tail query Postgres FTS** : à 10k+ articles, p99 search peut atteindre 1s. Mitigation : Meilisearch en v2.

### 11.3 Sécurité multi-tenant

- **Cross-tenant article leak** : tout queryset KB doit passer par `get_active_org` ou filter `organization=resolved_from_subdomain`. Ajouter un test E2E par défaut : "ouvre acme.showdesk.io/kb/?q=secret-de-bigcorp → ne renvoie rien".
- **Custom domain takeover** : si un client supprime son CNAME mais qu'on garde le mapping, un attaquant peut prendre le domaine et nous faire pointer dessus. **Mitigation** : DNS check périodique (Celery beat 1×/h), désactivation auto si CNAME cassé.
- **Magic link interception** : tokens OTP existants sont déjà 6 chiffres (faible). Pour magic link, utiliser un token URL-safe 32 chars + binding à user-agent partiel (fingerprint léger pour repérer le pivot).
- **Rate limit sur on-demand TLS** : sans `ask` endpoint qui valide le domaine, un attaquant peut épuiser des certs Let's Encrypt en spammant des CNAMEs vers `cname.showdesk.io`. → endpoint `ask` mandatory dès J1.
- **Status page DoS** : `/status` doit répondre même si DB down. → snapshot S3 régénéré, fallback Caddy `try_files`.

### 11.4 Coûts

- **Cloudflare for SaaS** : $0 jusqu'à 100 hostnames, $0,10/mois ensuite. À 1k clients = $90/mois → OK.
- **Email magic link volume** : 1 email par login. À 10k endusers actifs/mois × 2 logins = 20k emails. Gratuit chez Postmark < 10k/mois ; au-delà ~$10/mois. Acceptable.
- **Embeddings AI deflection** : à 100k articles indexés (1k articles × 100 orgs) × 1500 tokens/article = 150M tokens, $3 one-shot. Recompute incremental → négligeable.
- **OG image generation** : si dynamique via Satori/@vercel/og, ~3ms/image, cache S3 → quasi gratuit.

### 11.5 Risques produit

- **Sur-extension du scope MVP** : la liste v3 est tentante. Pour rester sur le north-star "all-in-one widget startups SaaS", il faut **shipper le MVP en 4 semaines max**, sinon on dilue l'avantage du widget vidéo.
- **Cannibalisation interne** : si le portail devient trop "central", les utilisateurs oublient le widget. → garder le widget comme entry point (CTA "Need help ? Click the widget" sur le portail).

---

## 12. Décisions à valider

1. [ ] **URL pattern par défaut** : `{slug}.showdesk.io` validé ? Ou préférer `help.showdesk.io/{slug}` (path-based) ?
2. [ ] **TipTap** validé comme éditeur ? (vs Lexical pour perf, vs Editor.js pour JSON-block).
3. [ ] **Postgres FTS** suffit en MVP ou démarrer direct sur Meilisearch ?
4. [ ] **Status page native** : oui en MVP (placeholder) + complète en v2 ? Ou full v2 d'office ?
5. [ ] **Custom domain en MVP** ou v2 ? (mon avis : v2, on n'a pas besoin de complexifier le MVP).
6. [ ] **Magic link auth réutilise `OTPCode` model** validé ? (vs créer `MagicLinkToken` séparé).
7. [ ] **Theming** : logo + couleur primaire suffisent en MVP ou ajouter font/layout ?
8. [ ] **Vidéothèque** : section dédiée ou simplement embed dans articles ?
9. [ ] **Robots.txt par défaut** : indexable (boost SEO Showdesk) ou opt-in (privacy par défaut) ?

---

## Sources

### Concurrents
- [eesel AI — Zendesk plans and pricing 2026](https://www.eesel.ai/blog/zendesk-plans-and-pricing)
- [eesel AI — Zendesk Guide subdomain vs custom domain](https://www.eesel.ai/blog/zendesk-guide-subdomain-vs-custom-domain)
- [Zendesk — Set up your custom domain](https://online-help.zendesk.com/hc/en-us/articles/360010100734)
- [Zendesk — Customizing your help center theme](https://support.zendesk.com/hc/en-us/articles/4408839332250)
- [Intercom — Set up custom domain Help Center](https://www.intercom.com/help/en/articles/1039696-set-up-a-custom-domain-for-your-help-center)
- [Intercom — Customize your Help Center](https://www.intercom.com/help/en/articles/56644-customize-your-help-center)
- [Intercom — Multiple Help Centers](https://www.intercom.com/help/en/articles/8170953)
- [Intercom Fin AI Agent outcomes](https://www.intercom.com/help/en/articles/8205718-fin-ai-agent-outcomes)
- [Intercom — Customer service metrics AI](https://www.intercom.com/blog/customer-service-metrics-ai/)
- [Crisp — Setup Knowledge Base custom domain](https://help.crisp.chat/en/article/setup-your-knowledge-base-domain-name-1fkjw73/)
- [Crisp — Knowledge Base features](https://crisp.chat/en/knowledge/customizable-knowledge-base/)
- [Plain.com — Product](https://www.plain.com/product)
- [Plain.com — Customer Infrastructure Platform 2026](https://www.plain.com/blog/customer-infrastructure-platform-2026)
- [Plain — Customer Support tools for startups 2026](https://www.plain.com/blog/startups-customer-support-tools)
- [Pylon — Customer Service KB software 2026](https://www.usepylon.com/blog/customer-service-knowledge-base-software)
- [eesel AI — Pylon honest review 2026](https://www.eesel.ai/blog/pylon)
- [eesel AI — Document360 vs Helpjuice](https://www.eesel.ai/blog/document360-vs-helpjuice)
- [Featurebase — Plain alternatives 2026](https://www.featurebase.app/blog/plain-alternatives)
- [Zendesk SEO problems](https://asadzulfahri.com/blog/4-reasons-why-zendesk-help-center-is-bad-for-seo/)

### Custom domain & SSL
- [Cloudflare for SaaS — Plans and pricing](https://developers.cloudflare.com/cloudflare-for-platforms/cloudflare-for-saas/plans/)
- [Cloudflare for SaaS — Custom domains use case](https://developers.cloudflare.com/use-cases/saas/custom-domains/)
- [Caddy — Automatic HTTPS](https://caddyserver.com/docs/automatic-https)
- [Caddy on-demand TLS guide (Five Nines)](https://fivenines.io/blog/caddy-tls-on-demand-complete-guide-to-dynamic-https-with-lets-encrypt/)
- [Skeptrune — Multi-tenant SaaS wildcard TLS DNS-01](https://www.skeptrune.com/posts/wildcard-tls-for-multi-tenant-systems/)
- [Building Multi-Tenant SaaS with Rails+Caddy+Kamal](https://mooktakim.com/blog/building-saas-with-rails-and-kamal/)
- [Olly — Custom domain support automatic TLS](https://olly.world/how-i-implemented-custom-domain-support-with-automatic-tls-certs-for-my-saas-app)
- [LowEndTalk — Cloudflare for SaaS >50k domains alt](https://lowendtalk.com/discussion/213319/alternative-to-cloudflare-for-saas-for-more-than-50k-custom-domains)

### Auth enduser
- [Stytch — Authenticate Magic Link B2B](https://stytch.com/docs/b2b/api/authenticate-magic-link)
- [Auth0 — Passwordless Magic Link](https://auth0.com/docs/authenticate/passwordless/authentication-methods/email-magic-link)
- [Ping Identity — What is Magic Link Login](https://www.pingidentity.com/en/resources/blog/post/what-is-magic-link-login.html)
- [Moxo — Client login security](https://www.moxo.com/blog/client-login-passwords-otp-magic-links-sso)
- [Supportbench — Customer portal authentication](https://www.supportbench.com/customer-portal-authentication-sso-magic-links-invite-only-access/)

### KB editors & search
- [TipTap vs Lexical vs Plate 2026 — BuildPilot](https://trybuildpilot.com/609-tiptap-vs-lexical-vs-plate-editor-2026)
- [Tiptap vs Lexical Slate Quill 2026 — pkgpulse](https://www.pkgpulse.com/blog/tiptap-vs-lexical-vs-slate-vs-quill-rich-text-editor-2026)
- [Best Rich Text Editors 2026 — Velt](https://velt.dev/blog/best-rich-text-editors-react-comparison)
- [Liveblocks — rich text editor framework 2025](https://liveblocks.io/blog/which-rich-text-editor-framework-should-you-choose-in-2025)
- [Django Postgres FTS docs](https://docs.djangoproject.com/en/6.0/ref/contrib/postgres/search/)
- [George London — Postgres fuzzy search trigrams](https://www.gjlondon.com/uncategorized/postgres-fuzzy-search-using-trigrams-django/)
- [Meilisearch vs Postgres FTS](https://www.meilisearch.com/docs/resources/comparisons/postgresql)
- [Meilisearch vs Algolia vs Typesense](https://www.meilisearch.com/blog/algolia-vs-typesense)
- [OneUptime — Django Postgres FTS 2026](https://oneuptime.com/blog/post/2026-01-27-django-postgresql-full-text-search/view)

### Status pages
- [Hyperping — Best Statuspage Alternatives 2026](https://hyperping.com/blog/best-statuspage-alternatives)
- [Better Stack — Free open-source status page tools](https://betterstack.com/community/comparisons/free-status-page-tools/)
- [Better Stack — Statuspage alternatives 2026](https://betterstack.com/community/comparisons/statuspage-alternatives/)
- [openstatus.dev — Best open-source status page 2026](https://www.openstatus.dev/guides/best-opensource-status-page-2026)
- [Cachet HQ on GitHub](https://github.com/cachethq/cachet)

### SEO & i18n
- [Hreflang Multilingual Guide 2026 — Digital Applied](https://www.digitalapplied.com/blog/international-seo-2026-hreflang-multilingual-guide)
- [Hreflang Implementation 2026 — LinkGraph](https://www.linkgraph.com/blog/hreflang-implementation-guide/)
- [Multilingual SEO best practices 2026 — Keytomic](https://keytomic.com/blog/multilingual-seo-best-practices)
- [Locize — What is i18n 2026](https://www.locize.com/blog/what-is-i18n/)
- [SimpleLocalize — auto-translate JSON 2026](https://simplelocalize.io/blog/posts/how-to-auto-translate-json-files/)

### Video embed
- [Loom Embed SDK — getting started](https://dev.loom.com/docs/embed-sdk/getting-started)
- [Crisp — Embed Loom videos in KB article](https://help.crisp.chat/en/article/how-can-i-embed-videos-from-loom-in-a-helpdesk-article-1vtsmvt/)
