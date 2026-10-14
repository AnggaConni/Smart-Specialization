# S³ Smart Specialization

**S³ (Smart Specialization Signals & Strategy)** is a lightweight, evidence-informed workspace for exploring regional capabilities, research signals, trade patterns, and possible specialization opportunities.

## Live pages

- **[S³ Landing page](https://anggaconni.github.io/Smart-Specialization/)** — project overview and navigation.
- **[Specialization Calculator](https://anggaconni.github.io/Smart-Specialization/calculator.html)** — structured assessment and reporting.
- **[Strategic Radar](https://anggaconni.github.io/Smart-Specialization/radar.html)** — analytics, regional explorer, interactive map, reported trade products and partner links, research records, news/policy discovery, and the **Policy Support Lab** for source-linked briefing drafts.

The Radar uses **English by default**, starts in the **bright theme**, and offers a dark-theme switch. The browser remembers the theme. The header contains a Google Translate widget. The Leaflet map supports dragging, mouse-wheel zoom and fullscreen mode. The regional explorer can request administrative boundaries when a country and ADM level are selected.

## What is connected today?

### Data APIs used by the weekly collector

| Provider / endpoint | What S³ uses it for | Access model |
|---|---|---|
| [OpenAlex Works API](https://docs.openalex.org/) | Scholarly metadata, publication dates, author affiliations where supplied, abstracts where supplied, and citation counts. | Basic queries work without a key. A free API key raises the usage budget; optional key is read from the **OPENALEX_API_KEY** Actions secret. |
| [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) | DOI and publisher-deposited bibliographic metadata; deduplication with OpenAlex results. | Public API, no signup/key required. The collector supports a contact email via **S3_CONTACT_EMAIL** or the configuration file to use the recommended polite pool. |
| [World Bank Indicators API v2](https://datahelpdesk.worldbank.org/knowledgebase/articles/889392) | Country names, capital/reference coordinates, region and income group, GDP, GDP per capita, population, and trade as a share of GDP. | Public API; no API key required. Missing observations remain unknown, not zero. |
| [UN Comtrade API](https://uncomtrade.org/docs/un-comtrade-api/) | Selected product-level import series and bilateral partner breakdowns from reporting importers. | A registered **free Basic Individual** account can request a subscription key, with free-tier limits. Without a valid key, S³ attempts the restricted public preview endpoint. Preview results may be truncated. |
| [GDELT DOC 2.0](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) | Source-linked news leads for configured themes: regional innovation, manufacturing, green industry, agri-food, trade/logistics, digital economy, and skills. | Public API; no API key required. The weekly pipeline searches a rolling 7-day window. Results are leads for human review—not verified events or facts. |

The collector writes a source-attributed snapshot to **data/radar-data.json**. The page reads this snapshot; it does not run the full collection pipeline from each visitor's browser.

**GDELT rate-limit handling:** the collector uses a dedicated low-volume request policy, bounded retries with exponential backoff and `Retry-After` handling, and stops querying remaining themes after a persistent HTTP 429. Successful topic results are retained; on partial refresh, recent prior news records fill missing themes where possible. The source registry marks partial/rate-limited/stale states instead of silently describing the feed as complete.

### Policy Support Lab: government and UN use

The **Policy Support Lab** creates a downloadable Markdown evidence brief for a selected country/market, sector focus, intended audience (government, UN Country Team/agency, development partner or regional organisation), planning horizon and user-entered decision question. It assembles the currently available World Bank indicators, relevant S³ research-theme records, reported trade observations and GDELT theme-matched news leads; then adds transparent candidate policy options for appraisal, candidate SDG alignments, monitoring questions and evidence gaps.

This is a **deterministic, source-linked drafting aid** using the published snapshot, not an AI-generated or validated policy recommendation. It does not claim an official UN/government position, score policy impact, calculate implementation costs, or infer province-level economic outcomes from boundaries. News matches are topic matches, not proof that an event occurred in the selected country. Analysts should check original sources, national development plans, laws, budget availability, distributional and environmental safeguards, and official SDG indicators before use.

The next major data integration recommended for this audience is the [UN Statistics Division SDG API](https://unstats.un.org/SDGAPI/swagger/) for official SDG indicator metadata/data, plus the [World Bank Projects API](https://datahelpdesk.worldbank.org/knowledgebase/articles/889386-developer-information-overview) and [Documents & Reports API](https://documents.worldbank.org/en/publication/documents-reports/api) for project and policy-document evidence. These are documented below as candidates and are not yet wired into S³.

### Geospatial and map services used in the browser

| Provider / tool | Use | Cost, key and caveats |
|---|---|---|
| [geoBoundaries API](https://www.geoboundaries.org/api.html) | On-demand ADM1/ADM2 province, state or district/county polygons when a user chooses a country and boundary level in the Regional Explorer. | Public API with no key for its public endpoints. Availability is not guaranteed. Read the returned boundary licence, source and year metadata; licences can vary by boundary/source. Provide attribution. Does **not** provide local economic indicators by itself. |
| [CARTO Basemaps](https://www.carto.com/basemaps/apikey/index.html) | Light/dark map tiles when a configured key is available. | Requires a key. CARTO currently documents a free allowance of up to **5 million requests/month for non-commercial use** and **1 million/month for commercial use**, subject to its terms. The browser key is visible to visitors and must be restricted by website referrer. |
| [OpenStreetMap tile service](https://operations.osmfoundation.org/policies/tiles/) | Fallback basemap if the CARTO browser configuration is absent or CARTO tiles fail. | No API key for standard tiles, but the public tile service is not an unlimited bulk/offline tile API. Keep attribution visible and follow its usage policy. For high-volume production use, consider a provider with an appropriate service plan. |
| [Leaflet](https://leafletjs.com/) | Interactive map, markers, GeoJSON polygons, popups and trade-link overlays. | Open-source JavaScript mapping library; not a statistical-data API. |
| [Chart.js](https://www.chartjs.org/) | Research, sector and trade charts. | Open-source visualization library; not a data API. |
| [Google Translate web widget](https://translate.google.com/) | Optional page translation from the header. | A third-party interface integration, not a translation-data API. Availability and behavior can change; dynamic map popups and chart labels may not always be translated consistently. |

**CARTO key setup:** the refresh workflow creates **data/map-config.json** from the repository Actions **variable** named **CARTO_API_KEY**. Do not hard-code the key into HTML or JavaScript. Since the value is delivered to a public browser, it is not a private credential. Restrict it to the deployed GitHub Pages referrer in the CARTO dashboard before adding it as a repository variable. An existing Actions secret by itself cannot be read by the public frontend without intentionally exposing it through a generated public config.

**UN Comtrade setup:** the workflow reads the Actions secret **UN_COMTRADE_API_KEY** (or the fallback name **COMTRADE_API_KEY**). If Comtrade rejects the key, the pipeline falls back to preview mode and labels the snapshot accordingly. If trade counts are small, check the workflow log and validate that the key is enabled for the API endpoint this collector uses.

**Optional OpenAlex key:** add **OPENALEX_API_KEY** under repository **Settings → Secrets and variables → Actions → Secrets** if you want the free-key budget. It is optional; the collector supports basic access without it.

## Regional Explorer: what can and cannot be inferred

The country explorer combines World Bank indicators, UN Comtrade product/partner records, and research records whose author-affiliation country metadata matches the selected country.

The map can show administrative geometries from geoBoundaries at ADM1 or ADM2 when the user requests them. Polygon selection identifies the administrative unit and displays the boundary's source, licence and represented year where supplied.

Important limits:

- Country-level GDP/population/trade indicators are **not** automatically distributed to provinces or districts.
- A polygon is a boundary, not evidence of local economic output, a particular factory, a supplier, a shipment route or a commercial opportunity.
- Research-affiliation matches reflect metadata coverage; they are not a full measure of research activity about a country.
- Trade links follow partner origin reported by the importing country. They are not verified company-to-company relationships.
- The geoBoundaries request happens when a user requests an ADM level; if the public endpoint, download host or browser CORS/network access fails, existing country/trade data remains usable.

## Additional free/open APIs for future S³ expansion

The options below are documented for future work; **they are not all integrated into the active collector yet**. Free access does not imply unlimited requests, universal coverage, or unrestricted reuse. Confirm terms, licences, API limits and attribution before enabling recurring jobs.

| API / dataset | Potential S³ use | Free access and current integration status |
|---|---|---|
| [World Bank Official Boundaries](https://datacatalog.worldbank.org/search/dataset/0038272/world-bank-official-boundaries) | Alternative Admin 0/1/2 polygons and region attributes. | Public dataset, CC BY 4.0; **candidate, not currently used**. The current on-demand polygon tool is geoBoundaries. |
| [UN Statistics Division SDG API](https://unstats.un.org/SDGAPI/swagger/) | Official SDG goal/target/indicator metadata and reported global/country series for progress monitoring and policy alignment. | Public API documentation and endpoints; confirm the relevant endpoint, geographies, series and update dates. **Candidate, not yet integrated.** |
| [World Bank Projects API](https://datahelpdesk.worldbank.org/knowledgebase/articles/889386-developer-information-overview) | Active, pipeline and closed development operations by country/sector, to identify existing programme portfolios and possible overlap. | Public API. It covers World Bank operations—not all government/UN/donor projects. **Candidate, not yet integrated.** |
| [World Bank Documents & Reports API](https://documents.worldbank.org/en/publication/documents-reports/api) | Find policy reports, economic updates, evaluations and development publications to expand the evidence base. | Public REST API for public documents; respect the source's metadata, links and reuse terms. **Candidate, not yet integrated.** |
| [OECD SDMX / Data Explorer API](https://www.oecd.org/en/data/insights/data-explainers/2024/09/api.html) | Regional GDP, gross value added, employment and productivity for regions covered by OECD datasets. | API access is free subject to OECD terms and rate limits; geographic coverage is not worldwide. **Not integrated yet.** |
| [Eurostat APIs](https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-introduction) | EU regional (NUTS) statistics, including economic structure and labour data. | REST access is free of charge; datasets have their own dimensions and definitions. **Not integrated yet.** |
| [FAOSTAT API developer portal](https://www.fao.org/statistics/highlights-archive/highlights-detail/faostat-launches-a-new-api-developer-portal-to-make-data-access-easier/en) | Agriculture, production, food balances and related specialisation context. | FAO announced free programmatic API access in April 2026 with coverage of more than 245 countries and territories. Check the portal's endpoint documentation before building a collector. **Not integrated yet.** |
| [UNIDO Statistics Portal API](https://stat.unido.org/unido-statistics-portal-api) | Manufacturing structure, industry, national accounts and manufacturing trade. | UNIDO states its listed databases are accessible free of charge without registration. Check dataset metadata, licence/attribution notes and endpoint availability. **Not integrated yet.** |
| [OpenAQ API](https://docs.openaq.org/) | Air-quality and environmental context for green-transition exploration. | API key required. The documented general-use tier is free, with a rate limit of 60 requests/minute and 2,000/hour; higher limits require a custom arrangement. Environmental observations are not direct indicators of industrial competitiveness. **Not integrated yet.** |
| [GBIF API](https://www.gbif.org/developer/summary) | Biodiversity observations and ecosystem context, where relevant to place-based opportunities. | Public occurrence API with responsible-use limits; individual datasets retain their licences. **Not integrated yet.** |

**Suggested expansion order:** (1) wire the UN SDG API into an official indicator panel with series, units, disaggregation and reference years; (2) ingest World Bank project/document metadata with country/sector filters and overlap checks; (3) add regional indicators only where authoritative data and geographic codes align; (4) add FAOSTAT/UNIDO datasets for sector-specific evidence; (5) expand GDELT topics only with backoff, caching and a bounded query budget. Preserve each record's source, date, geography, coverage, licence and uncertainty.

## Weekly refresh and manual run

The workflow **S3 Radar weekly data refresh** is scheduled for every Monday at **09:17 WIB** and can also be run manually:

1. Open the repository's **Actions** tab.
2. Select **S3 Radar weekly data refresh**.
3. Select **Run workflow**.
4. Review the collector, JSON validation, and publish/commit steps.

The dashboard's **Reload snapshot** button downloads the latest published JSON; it does not trigger collection. If an API fails, the pipeline records warnings and attempts to retain the previous usable snapshot rather than publishing an empty one.

## Local development

Requires Python 3.11+ and Node.js.

    python -m pip install -r requirements.txt
    python -m unittest discover -s tests -v
    node --check radar.js
    python -m http.server 8080

Open http://localhost:8080. For current data, run python pipeline/collect_radar.py and ensure data/radar-data.json has been generated. geoBoundaries polygons are requested from its public API when needed by the browser.

## Repository layout

- index.html — landing page.
- calculator.html — specialization calculator.
- radar.html — responsive dashboard, map controls, themes and regional/news sections.
- radar.js — map, geoBoundaries overlay, filters, signal/news views, charts, regional profiles and CSV export.
- pipeline/collect_radar.py — OpenAlex, Crossref, World Bank, UN Comtrade and GDELT collectors.
- config/radar_sources.json — markets, topic searches and collection parameters.
- data/radar-data.json — weekly snapshot consumed by GitHub Pages.
- data/map-config.json — generated browser map-provider configuration; a restricted browser CARTO key may be public in this file.
- tests/ — data transformation and dashboard integration tests.
- .github/workflows/refresh-radar.yml — weekly/manual collection and publishing.
- .github/workflows/ci.yml — tests, HTML/DOM checks, JSON validation and JavaScript syntax checks.

## Interpretation and responsible use

- News results are source-discovery leads. Open the publisher's original page and corroborate claims before treating them as evidence.
- Research records are bibliographic discoveries, not proof of market demand or commercial impact.
- UN Comtrade values are reported imports, not retail sales, revenue, profit or confirmed orders.
- GDELT source-country metadata does not guarantee that the reported event occurred in that country.
- Country reference coordinates generally point to capitals, not factories, ports or production zones.
- Discovery/freshness scores are triage aids, not validated impact, risk or investment scores.
- Respect API terms, rate limits, attribution requirements and the rights of source publishers. The collector stores source-linked metadata rather than republishing full article text.

Project code is distributed under the repository's MIT license. Data, API responses, basemaps and third-party code remain subject to the respective providers' terms.
