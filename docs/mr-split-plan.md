# Rozdělení mých commitů v coinjoin-emulator na malé MR

Stav k 2026-11-15. Stack je postavený jako lokální větve (sekce Stavba); nic není pushnuté, PR
neexistují a `main` se nepřepisoval.
Vzor je stejný jako u coinjoin-analysis (stack #24) a blocksci (stacky #39 a #42): malé PR ve
forku `OndrejMan/coinjoin-emulator`, které si projdeš sám, než něco pošleš do crocs-muni.

## Výchozí stav

- `main` bez commitu s tímto plánem = `02b20e47` = `origin/main`, strom `35b29e72a0df`. Kde plán
  říká „strom `main`“, myslí tento strom.
- Spodek stacku je `original-rajnoha-branch` (`dd87648b`): 33 Rajnohových commitů nad
  `origin/upstream` (`b70f5ddb`). To je otevřený PR #8 a plán na něj nesahá.
- Rozsah je `original-rajnoha-branch..main` po prvním rodiči, tedy 220 commitů
  (+14 390 −1 073 řádků, 156 souborů):
  - 214 mých commitů,
  - 2 merge commity crocs-muni `main` (č. 183 mining fee rate, č. 189 get_history),
  - 4 commity Davida Rajnohy z PR #11 a #12 (č. 190–193).
- Dnes jsou ty commity ve dvou velkých PR: #7 `robustness-and-reproducibility` →
  `original-rajnoha-branch` (č. 1–193) a #14 `main` → `robustness-and-reproducibility`
  (č. 194–220).
- `origin/upstream` je crocs-muni `main` z února. Skutečný crocs-muni `main` je `f73f2361`
  a má navíc 8 oprav z `devel`, které v `main` nejsou (viz rozhodnutí 1).
- Po plánu přibyly na `main` dva commity: „fix(kubernetes): delete a stopped client's service even
  when its pod is gone“ (č. 221, MR 33 za č. 146) a 2026-11-15 „fix(wasabi): stop watching the
  configuration in the 2.6.0 images“ (č. 222, MR 44, dřívější necommitnuté úpravy Dockerfile).
- Tagy `mr-01-*` až `mr-11-*` a `INTEGRATION_PLAN.md` patří ke staré větvi `rajnoha-on-crocs`
  a s tímto plánem nesouvisí.

## Jak je plán ověřený

Pomocné skripty jsou mimo repo v `diplomka/docs/coinjoin-emulator-mr-split/` (repo jen čtou,
objekty a exporty zapisují do `/tmp/emulator-mr-split`):

1. `inventory.py` očísluje commity a z `git blame` spočítá textové závislosti (commit mění
   řádky, které přidal dřívější commit, nebo s nimi sousedí).
2. `plan.py` drží rozdělení. Žádný commit nepředbíhá commit, na kterém textově závisí.
3. `replay.py` přehraje všech 220 commitů v plánovaném pořadí (cherry-pick v paměti, merge jako
   diff proti prvnímu rodiči). Výsledek: žádný konflikt a konečný strom je shodný s `main`.
4. `gate.py` pustil `pytest -m "not integration"` na každém z 220 přehraných commitů a ruff,
   mypy a pylint na tipu každého MR (ruff 0.16.6, mypy 2.3.1, pytest 9.1.1, `.venv` emulátoru).
   Pro srovnání běžel pytest i na všech 220 původních commitech.

Neběželo: žádná emulace, žádný build image, test `integration` a pylint, mypy a ruff na
jednotlivých commitech uvnitř MR. Textová závislost není sémantická: skryté závislosti ukázal
až pytest.

## Co jsem při průchodu našel

1. **Čtyři testy z č. 31 jsou červené až do č. 108 a 116, už v dnešní historii.**
   „feat(joinmarket): export round event artifacts“ přidává
   `test_live_round_count_advances_only_for_mined_destination`,
   `test_live_round_count_ignores_rpc_start_without_chain_match`,
   `test_live_round_count_ignores_a_malformed_rpc_txid` (č. 106 ho přejmenuje na `…rejects…`)
   a `test_a_tumbler_without_labels_marks_the_evidence_incomplete`. První tři projdou až
   s „fix(joinmarket): count only CoinJoin rounds that were actually mined“ (č. 108), čtvrtý
   s „fix(joinmarket): mark tumbler label evidence as incomplete“ (č. 116). V původní historii
   je kvůli tomu červených 85 commitů, v plánovaném pořadí tipy MR 08–36. Oprava: testy
   přesunout do commitů, které je splní.
2. **Špatné pořadí importů v `tests/test_kubernetes_driver_contract.py` od č. 99 do č. 146**
   (ověřeno na přehraném pořadí).
   „fix(kubernetes): retry without port sysctl after API rejection“ vloží `from copy import
   deepcopy` na špatné místo (ruff I001) a srovná to až „fix(kubernetes): wait for a stopped
   pod to disappear before returning“. Oprava: správné pořadí rovnou v č. 99.
3. **mypy hlásí dvě chyby od zavedení konfigurace (č. 35) do č. 42**
   (návratový typ `ProducerLabelEvidence` ve `wasabi_engine.py` a `joinmarket_engine.py`,
   kód z č. 29 a 31). V původním pořadí přichází
   CI workflow (č. 38) před opravou, takže by první PR s workflow byl červený. V plánu je proto
   „chore(types): enable strict mypy incrementally“ (č. 42) před workflow; červený zůstane jen
   tip MR 10, kde CI ještě neexistuje.
4. **Merge č. 183 rozbije dva testy startu koordinátoru až do č. 186**
   („fix(wasabi): synchronize coordinator configuration startup“). Proto jsou merge, oprava
   `MiningFeeRate` (č. 184), č. 186 a č. 220 v jednom MR.
5. **Č. 80 je záměrně červený test** před opravou č. 81 (base64 u stahování archivů). Zůstává.
6. **Čtyři posuny submodulu `vendor/joinmarket-clientserver`** (č. 170, 173, 178, 180). Dva
   z nich ukazují na commity `a5fad859` a `8702906b`, které po přepisu už nejsou na `master`
   forku, takže checkout submodulu na těch mezistavech není spolehlivý. Návrh: jeden commit
   s posunem na `6ab866f`.
7. **Č. 149 je hned přepsaný č. 150.** „merge the manager's stderr into stdout“ zavede
   `stderr=STDOUT` a „stream stdout and stderr concurrently“ to vrátí a čte obě roury zároveň.
   Návrh: squash.
8. **Testy historických archivů (č. 37, 62, 160) v CI nic netestují.** Čtou `testing_data`
   vedle repa a bez něj se přeskočí. Č. 62 opravuje test z č. 37 poté, co č. 61 začal odmítat
   plochá pole; v plánu jde č. 37 až za č. 61, takže č. 62 patří squashnout do č. 37.
9. **Č. 219 není rozpracovaný, ale leží nad WIP commity č. 216–218.** „fix(joinmarket): export
   daemon logs for coinjoin analysis“ sousedí v `joinmarket_engine.py` s metodou z č. 218.
   Přesun pod WIP znamená jeden triviální konflikt (provedeno: č. 219 je v MR 39).
10. **Čtyři Rajnohovy commity (č. 190–193) jsou uprostřed mých.** Na „fix(kubernetes): spool
    downloaded archives to disk…“ textově závisí č. 205 a č. 214, takže nejdou vynechat.
    Tvoří vlastní MR 50 se zachovaným autorem.
11. **crocs-muni mezitím opravil část stejných chyb.** `194bf146` je stejná oprava jako č. 184,
    `afdf9e0d` jako jádro č. 175 a `2a1f09ed` ruší `skip_rounds`, které opravuje č. 157
    (č. 206 s ním textově sousedí). `6c595423`, `b93c1287`, `87a2c934` a `dde60b54` mění stejné
    soubory a témata jako č. 162, 66/129, 67 a 60/61; řádek po řádku jsem je neporovnával.
    Zkušební merge `upstream/main` do `main` má konflikty v 6 souborech
    (`manager.py`, `configuration.py`, `engine_base.py`, `wasabi_engine.py` a oba
    `mining_fee_rate.patch`).
12. **Commit messages:** 91 commitů nemá tělo (24 z 25 oprav zděděného kódu, kontrakt, tooling
    a řada pozdějších), 20 má víc než jednu větu nebo víc řádků, tři začínají „WIP“. Při přepisu
    je levné to srovnat.

## Rozdělení: 57 MR ve 12 vlnách

Vlna je jeden GitHub stack. První má base `original-rajnoha-branch`, každá další nejvyšší větev
předchozí vlny (jako druhý stack v blocksci). Čísla commitů jsou z inventáře na konci, `M` je
merge, `37+62` je squash, `U301` cherry-pick z crocs-muni, ~~přeškrtnutý~~ vypuštěný commit a „+ N nové“ dorovnávací
nebo nové commity. +/− je součet původních commitů. „Testy na tipu“ je stav postavené
větve: pytest bez `integration`, od MR 10 i ruff, mypy a pylint. Pro diplomku jsou klíčové vlny
2, 6, 8, 10 a 11 (kontrakt s pipeline, Kubernetes, Wasabi, postmix, souběžné běhy).

### Vlna 1: Opravy zděděného kódu

| MR | Větev | Název PR | Commity | +/− | Testy na tipu |
|---|---|---|---|---|---|
| 01 | `pr/01-inherited-cleanup` | Fix imports, bare excepts and type slips in the inherited code | 1, 2, 3, 4, 5 | +39 −29 | bez testů, compileall prošel |
| 02 | `pr/02-bitcoin-wasabi-timeouts` | Raise on Bitcoin and Wasabi timeouts instead of continuing | 6, 7, 8, 19, 20 | +48 −27 | bez testů, compileall prošel |
| 03 | `pr/03-joinmarket-inherited-fixes` | Fix JoinMarket configuration reads and startup guards | 9, 10, 11, 25 | +70 −37 | bez testů, compileall prošel |
| 04 | `pr/04-engine-funding-fixes` | Fix distributor funding, exit paths and block export errors | 13, 14, 15, 16, 17, 18, 24 | +37 −17 | bez testů, compileall prošel |
| 05 | `pr/05-remote-runner-fixes` | Fix the remote helper and scenario runner contracts | 12, 21, 22, 23 | +35 −5 | bez testů, compileall prošel |

### Vlna 2: Kontrakt s pipeline

| MR | Větev | Název PR | Commity | +/− | Testy na tipu |
|---|---|---|---|---|---|
| 06 | `pr/06-run-identity-markers` | Add a deterministic run identity and controller completion markers | 26, 27 | +271 −5 | 14 passed |
| 07 | `pr/07-artifact-layout-manifest` | Write artifacts into a fixed layout with a producer label manifest | 28, 29, 59, 64 | +302 −19 | 22 passed |
| 08 | `pr/08-joinmarket-round-events` | Record and export JoinMarket round events | 30, 31 | +946 −2 | 49 passed |

### Vlna 3: Build, CI a statická analýza

| MR | Větev | Název PR | Commity | +/− | Testy na tipu |
|---|---|---|---|---|---|
| 09 | `pr/09-image-publishing` | Publish the emulator container images from CI | 32, 33, 52, 171 | +320 −53 | 49 passed |
| 10 | `pr/10-lint-config` | Add uv project metadata and the Ruff, mypy and pylint configuration | 34, 35, 36, 123 | +318 −126 | 50 passed, mypy červený |
| 11 | `pr/11-strict-mypy` | Enable strict mypy incrementally | 42 | +404 −3 | 50 passed |
| 12 | `pr/12-static-analysis-ci` | Run tests and static analysis in CI on locked uv dependencies | 38, 39, 40, 41, 47 | +1410 −24 | 50 passed |
| 13 | `pr/13-manager-image-fixes` | Fix the manager image for other architectures and non-root users | 46, 48, 49, 50 | +9 −4 | 50 passed |

### Vlna 4: Bitcoin node

| MR | Větev | Název PR | Commity | +/− | Testy na tipu |
|---|---|---|---|---|---|
| 14 | `pr/14-btc-node-container` | Make the btc-node container start and mine reliably | 43, 44, 126 | +92 −19 | 54 passed |
| 15 | `pr/15-btc-wallet-rpc` | Route wallet RPCs correctly and support descriptor-only Bitcoin Core | 53, 54, 55 | +114 −24 | 57 passed |
| 16 | `pr/16-btc-readiness-mining` | Wait for a synchronized node and verify mining results | 58, 127, 128 | +347 −21 | 67 passed |

### Vlna 5: Konfigurace, engine a CLI

| MR | Větev | Název PR | Commity | +/− | Testy na tipu |
|---|---|---|---|---|---|
| 17 | `pr/17-nested-wallet-config` | Read nested wallet settings and reject incomplete JoinMarket scenarios | U301, 60, 61, 63 | +239 −96 | 80 passed |
| 18 | `pr/18-historical-archive-tests` | Test the archive contract against historical runs | 37+62, 160 | +376 −24 | 82 passed |
| 19 | `pr/19-engine-client-failures` | Abort when clients fail to start and keep unpaid funding for retry | 65, U305, 66, 129 + 1 nové | +193 −39 | 88 passed |
| 20 | `pr/20-joinmarket-vendored-fork` | Vendor the JoinMarket fork and isolate Core wallets | 56, 57, 124, 170+173+178+180 | +208 −34 | 92 passed |
| 21 | `pr/21-cleanup-lifecycle-cli` | Complete every cleanup step and tighten the CLI flags | U304, 67, 71, 72, 76 + 1 nové | +187 −40 | 99 passed |
| 22 | `pr/22-pipeline-cli-options` | Honor pipeline image overrides, node options and raw datadir download | 68, 69, 70 | +282 −24 | 106 passed |
| 23 | `pr/23-service-endpoints` | Resolve service endpoints consistently across drivers | 73, 74 | +257 −36 | 126 passed |
| 24 | `pr/24-shared-bitcoin-datadir` | Keep a shared Bitcoin datadir readable and make the initial block count configurable | 88, 125 | +75 −7 | 129 passed |

### Vlna 6: Drivery

| MR | Větev | Název PR | Commity | +/− | Testy na tipu |
|---|---|---|---|---|---|
| 25 | `pr/25-kubernetes-cleanup-quota` | Scope Kubernetes cleanup to the run and fail fast on quota or a missing pod IP | 75, 77, 78, 145 | +198 −44 | 136 passed |
| 26 | `pr/26-kubernetes-archive-download` | Make Kubernetes archive downloads binary-safe and bounded | 79, 80, 81, 82, 83, 84, 85, 86, 174 | +335 −130 | 158 passed |
| 27 | `pr/27-kubernetes-uploads` | Upload files to Kubernetes pods through checked, chunked commands | 87, 89, 185 | +207 −20 | 167 passed |
| 28 | `pr/28-docker-artifacts` | Keep Docker containers until their artifacts are collected | 90, 91, 92 | +67 −6 | 170 passed |
| 29 | `pr/29-podman-native-api` | Use the native Podman API and retain containers until cleanup | 93, 94, 95, 96, 97 | +281 −41 | 183 passed |
| 30 | `pr/30-port-reservation` | Reserve the Wasabi service ports in every container | 98, 99, 100, 101 | +117 −16 | 186 passed |
| 31 | `pr/31-driver-logs-state` | Expose container logs, state and memory usage through the drivers | 136, 140, 155, 169 | +111 −1 | 189 passed |
| 32 | `pr/32-local-cleanup-ownership` | Scope local cleanup by ownership and fix uploaded file owners | 158, 159, 179, 202 | +365 −66 | 203 passed |
| 33 | `pr/33-kubernetes-pod-lifecycle` | Wait for deleted pods and tie resources to the controller pod | 146, 221, 181 | +140 −11 | 209 passed |

### Vlna 7: JoinMarket

| MR | Větev | Název PR | Commity | +/− | Testy na tipu |
|---|---|---|---|---|---|
| 34 | `pr/34-joinmarket-local-base-build` | Build the vendored JoinMarket base image locally | 45, 51, 120, 121, 122 | +159 −22 | 214 passed |
| 35 | `pr/35-joinmarket-startup` | Harden JoinMarket wallet startup and the scenario block clock | 102, 103, 104, 105, 176, 172 | +335 −30 | 226 passed |
| 36 | `pr/36-joinmarket-destination-matching` | Reconcile JoinMarket round events with explicit conflict statuses | 106, 107, 156, 163, 164 | +615 −77 | 252 passed |
| 37 | `pr/37-joinmarket-round-limits` | Count only mined JoinMarket rounds and stop at the limit | 108, 109, 115, 116, 119 | +162 −7 | 262 passed |
| 38 | `pr/38-joinmarket-taker-pacing` | Pace takers by mined attempts and make their timeout configurable | 110, 111, 112, 113, 114, 165, 166 | +421 −81 | 283 passed |
| 39 | `pr/39-joinmarket-wallet-export` | Export every derived JoinMarket address and the daemon logs | 117, 118, 219 | +235 −37 | 288 passed |

### Vlna 8: Wasabi

| MR | Větev | Název PR | Commity | +/− | Testy na tipu |
|---|---|---|---|---|---|
| 40 | `pr/40-wasabi-readiness` | Bound Wasabi readiness waits and wait for started wallets | 130, 161, 177 | +156 −21 | 299 passed |
| 41 | `pr/41-wasabi-round-semantics` | Count broadcast Wasabi rounds, stop at the round limit and drop skip_rounds | U303, 131, 132, 133, 134, 162, ~~157~~, U308, 206 | +260 −125 | 306 passed |
| 42 | `pr/42-wasabi-coordinator-startup` | Retry coordinator startup and make the distributor timeout configurable | 135, 137, 138 | +205 −33 | 316 passed |
| 43 | `pr/43-wasabi-rpc-retries-liveness` | Retry racy Wasabi RPCs, name dead clients and collect their logs | 139, 182, 141, U302, U307, 175 | +244 −30 | 327 passed |
| 44 | `pr/44-wasabi-images` | Make the pinned Wasabi images build reproducibly and start reliably | 142, 143, 144, 187, 188, 222 | +56 −28 | 327 passed |
| 45 | `pr/45-upstream-sync-mining-fee` | Merge crocs-muni main (mining fee rate) and synchronize the coordinator start | 183M, U306, ~~184~~, 186, 220 | +494 −58 | 336 passed |
| 46 | `pr/46-wasabi-client-patches` | Patch the 2.6.0 client: broadcast errors and the block filter race | 203, 213 | +54 −0 | 336 passed |

### Vlna 9: Vzdálené řízení a runner

| MR | Větev | Název PR | Commity | +/− | Testy na tipu |
|---|---|---|---|---|---|
| 47 | `pr/47-remote-status` | Report remote simulation status and deployment failures correctly | 147, 148, 152, 153 | +113 −18 | 340 passed |
| 48 | `pr/48-runner-output` | Stream the manager output from the scenario runner without deadlocks | 149+150, 151, 154 | +174 −16 | 343 passed |
| 49 | `pr/49-upstream-sync-get-history` | Merge crocs-muni main: get_history in client logs | 189M | +13 −0 | 343 passed |
| 50 | `pr/50-rajnoha-remote-cli-pvc` | Remote CLI, spooled archive downloads and a PVC workspace (David Rajnoha) | 190, 191, 192, 193 | +501 −31 | 349 passed |

### Vlna 10: Likvidita a postmix

| MR | Větev | Název PR | Commity | +/− | Testy na tipu |
|---|---|---|---|---|---|
| 51 | `pr/51-postmix-config` | Parse postmix spend schedules and scenario metadata | 194, 195, 200 | +157 −10 | 363 passed |
| 52 | `pr/52-wasabi-postmix-spends` | Send scheduled Wasabi postmix spends | 196, 197, 198, 199, 201, 204 | +509 −21 | 375 passed |
| 53 | `pr/53-postmix-coin-selection` | Let a postmix spend choose its coins by amount | 207, 208, 209, 215 | +251 −25 | 388 passed |

### Vlna 11: Snapshot, souběžné běhy a diagnostika

| MR | Větev | Název PR | Commity | +/− | Testy na tipu |
|---|---|---|---|---|---|
| 54 | `pr/54-bitcoin-datadir-snapshot` | Copy the Bitcoin datadir as a flushed, frozen snapshot | 167, 168 | +335 −13 | 400 passed |
| 55 | `pr/55-kubernetes-concurrent-runs` | Isolate concurrent runs in a shared Kubernetes namespace | 205, 211 | +203 −31 | 407 passed |
| 56 | `pr/56-run-log-failure-report` | Keep the manager log in the artifacts and report pod states on failure | 210, 214, 212 | +335 −36 | 417 passed |

### Vlna 12: JoinMarket: plány peněženek a postmix (rozpracováno)

| MR | Větev | Název PR | Commity | +/− | Testy na tipu |
|---|---|---|---|---|---|
| 57 | `pr/57-joinmarket-schedules-postmix` | WIP: JoinMarket wallet schedules and postmix withdrawals | 216, 217, 218 | +664 −41 | 441 passed |

Poznámky k rozdělení:

- **Pořadí vln kopíruje dnešní historii.** JoinMarket nejde levně odsunout za Wasabi a postmix:
  č. 69 (CLI) stojí na č. 57 a konfigurace postmixu (č. 194, 195) na č. 110 a 119.
- **Vlna 1** nemá testy (adresář `tests` vzniká až v č. 26); kontrola je import a kompilace.
- **MR 20** nese submodul forku JoinMarketu a všechny jeho posuny pohromadě; žádný pozdější
  commit na nich textově nezávisí.
- **MR 24** vznikl kvůli závislosti: č. 125 sousedí s č. 88, které potřebuje č. 73.
- **Driver API jsou u driverů, ne u spotřebitelů** (MR 31: logy, stav, paměť). Výjimka je
  pause/unpause (č. 167), které jde se snapshotem datadiru v MR 54, a build argumenty (č. 121)
  s lokálním buildem base image v MR 34.
- **MR 45 a 49 obsahují skutečné merge commity** crocs-muni `main`. Při stavbě se merge
  zopakuje a strom se vezme z přehrání, takže druhý rodič zůstane zachovaný.
- **MR 57 je draft** (tři WIP commity). Č. 219 je v MR 39, takže dřívější MR 58 zanikl (nález 9).
- **Run log (MR 56) je až za postmixem**, protože č. 214 sousedí s háčky z č. 197.

## Úpravy při stavbě

Všechny jsou provedené (2026-11-15). Strom vrcholu je shodný s `main` bez tohoto plánu.

| Úprava | Commity | Důvod |
|---|---|---|
| Přesun testů | 3 testy z č. 31 (s přejmenováním z č. 106, třídou `EventNode` a importy `cast` a `pytest`) do č. 108, 1 test z č. 31 do č. 116 | nález 1 |
| Oprava pořadí importů | z č. 146 do č. 99 | nález 2 |
| Squash | č. 170 + 173 + 178 + 180 → jeden posun submodulu z `35f9439` na `6ab866f` | nález 6 |
| Squash | č. 150 do č. 149 | nález 7 |
| Squash | č. 62 do č. 37 | nález 8 |
| Přesun | č. 219 z MR 58 do MR 39 | nález 9 |
| Messages | 106 commitů má nové tělo s jednou větou „proč“ (`messages.json`); subjecty zůstaly, „WIP“ jen u č. 216–218 | nález 12 |

Po squashích je to 217 commitů v 57 MR (211 mých, 2 merge, 4 Rajnohovy).

## Rozhodnutí, která potřebuju od tebe

1. **Base a crocs-muni `main`.** Doporučuju dva kroky:
   - *Teď:* postavit stack nad `original-rajnoha-branch`, jak je (merge commity zůstanou
     v MR 45 a 49). Strom vrcholu je shodný s `main`, takže se nic neztratí a dá se to dokázat.
   - *Před odesláním do crocs-muni:* nejdřív běžný merge `upstream/main` do `main` (6 souborů
     s konflikty, pak sada testů), potom rebase Rajnohových 33 commitů a celého stacku na
     `f73f2361` s kontrolou stromu proti tomu merge. MR 45 a 49 tím zaniknou, č. 184 vypadne
     (upstream má stejnou opravu), č. 157 ztratí smysl (upstream `skip_rounds` zrušil) a Rajnohovy
     commity se při řešení konfliktů změní.

   Druhá možnost je udělat rebase na crocs-muni `main` rovnou. Stack je pak čistě lineární,
   ale práce je víc a bez předchozího merge v `main` není proti čemu porovnat strom.

   Rozhodnuto 2026-11-14: stack zůstane nad `original-rajnoha-branch`, rebase na crocs-muni
   `main` se teď nedělá.
2. **Hrubost.** 58 MR má průměrně 4 commity a ~250 řádků. Jestli je to moc, dá se otevřít
   12 PR po vlnách (stejné hranice, bez dalšího přeskládání).
   Rozhodnuto 2026-11-15: 58 malých MR. Po přesunu č. 219 do MR 39 jich je 57.
3. **Squashe a přesuny testů** z tabulky výše: všechny, nebo jen některé?
   Rozhodnuto 2026-11-15: všechny, včetně přesunu č. 219 pod WIP commity. Messages: srovnat
   všechny; Rajnohovy a merge commity zůstávají beze změny.
4. **WIP commity č. 216–218:** draft PR navrchu, nebo zatím mimo stack? A přesunout č. 219 pod ně?
   Rozhodnuto 2026-11-14: WIP commity zůstanou ve stacku jako draft PR navrchu.
5. **Rajnohovy č. 190–193:** nechat jako MR 50 uprostřed (doporučuju), nebo je chceš jinde?
   Rozhodnuto 2026-11-15: vlastní MR 50 se zachovaným autorem i messages.
6. **PR #7 a #14:** nechat otevřené, dokud stack neprojdeš, a pak zavřít? PR #8 zůstává spodkem.
7. **Otevírání:** rozhodnuto 2026-11-13: všechny PR najednou, až budou větve postavené
   a ověřené (ne po vlnách).

Otevřené zůstává jen rozhodnutí 6; týká se až otevírání PR.

## Stavba (2026-11-15)

- Větve `pr/01-…` až `pr/57-…` na hranicích MR, každá nad předchozí, a `stack/mr-split` (= `pr/57-…`).
  Záloha `main` je `backup/mr-split-20261115/main` (`d061369a`). `main` ani pracovní strom se neměnily.
- Postavil to `build.py` v `diplomka/docs/coinjoin-emulator-mr-split/`: přehraje pořadí z `plan.py`
  jako `replay.py`, úpravy z tabulky dělá nad stromy a messages bere z `messages.json`. Autor,
  committer a data jsou z původních commitů, merge č. 183 a 189 mají původního druhého rodiče.
  Opakované spuštění vyrobí stejné commity.
- Strom `stack/mr-split` je strom `main` bez `docs/mr-split-plan.md`.
- `verify.py` porovnal diff každého commitu s originálem. Jinak než v kontextu se liší jen č. 31, 99,
  106, 108, 116 a 146 (úpravy z tabulky) a č. 156 a 164, které měnily přesunuté testy; ty změny jsou
  teď v č. 108 a 116. Squashe jsou zkontrolované ručně.
- Konflikty vznikly jen u přesunutého č. 219 a pak u č. 218 nad ním. `build.py` je řeší tak, že metoda
  `store_client_logs` zůstává pod `store_engine_data` jako na `main`.
- `gate.py` na všech 217 commitech: pytest je červený jen na č. 80 (záměrný test, nález 5)
  a na č. 183 a 184 uvnitř MR 45 (nález 4). Na tipech prošly ruff, mypy i pylint, kromě mypy na tipu
  MR 10 (nález 3, CI tam ještě není). Vlna 1: `compileall` a import všech modulů `manager` na každém
  commitu bez chyby. Výsledky jsou v `gate.json`, stav z plánu v `gate-plan.json`.
- Neběželo: emulace, build images, testy `integration` a lint na commitech uvnitř MR.

## Cherry-picky z crocs-muni `main` (2026-11-15)

Na tvoje přání jsou ve stacku i nové commity crocs-muni `main` (`f73f2361`, autor Antonín Dufka).
Každý je cherry-pick s původním autorem a řádkem `(cherry picked from commit …)`. Stojí v MR, který
řeší totéž, hned před naším odpovídajícím commitem; naše commity za ním ho doupravují. Konflikty
s naším kódem jsou vyřešené v cherry-picku (`resolutions/`, `edits.json`), aby každý commit prošel testy.

| Upstream | MR | Před | Výsledek |
|---|---|---|---|
| `dde60b54` Fix config loading with new format | 17 | č. 60 | naše č. 60 a 61 ho doupravují (generátory, odmítnutí plochých polí) |
| `b93c1287` Fix wallet funds addressing with failed clients | 19 | č. 66 | č. 66 ukončí běh; dorovnávací commit vrací párování, které je pak zbytečné |
| `87a2c934` Improve container cleanup | 21 | č. 67 | č. 67 nahradí cleanup; dorovnávací commit vrací tolerantní ukládání dat klienta |
| `6c595423` Fix round counter restarts when coordinator poll fails | 41 | č. 131 | č. 131 počítá kola z broadcastů |
| `2a1f09ed` Drop skip_rounds | 41 | místo č. 157 | převzato beze zbytku; č. 157 vypuštěn |
| `afdf9e0d` Fix wasabi client data path | 43 | č. 175 | č. 175 už jen pojmenuje cestu a přidá test |
| `12528c49` Unify backend naming in log collection | 43 | č. 175 | převzato: logy backendu 2.6 jsou v `data/wasabi-backend` |
| `194bf146` Fix failure with null mining fee rate | 45 | místo č. 184 | převzato; č. 184 (stejná oprava) vypuštěn |

Rozhodnutí 2026-11-15: skip_rounds zrušit (nikde se nepoužívá, všech 2 732 výskytů ve scénářích
a bězích je `null`), při selhání klientů ukončit běh (naše), jméno `wasabi-backend` (upstream),
u shodných oprav nechat jejich commit a náš zmenšit nebo vypustit.

Výsledek: 225 commitů v 57 MR (217 − č. 157 a 184 + 8 cherry-picků + 2 dorovnávací). `gate.py`
na všech commitech: pytest červený jen na č. 80 a uvnitř MR 45 na merge č. 183 a cherry-picku `194bf146`
(dva testy startu koordinátoru do č. 186); lint čistý kromě mypy na tipu MR 10. Force-push 41 větví
(MR 17 až 57) s lease na pushnutý stav (záloha `backup/mr-split-20261115-pushed/*`), PR zůstaly otevřené
drafty; nové názvy a popisy mají PR #31, #33, #35, #55, #57 a #59.

Strom vrcholu = `main` bez plánu + zrušené skip_rounds, `data/wasabi-backend`, `ADDR_WASABI_BACKEND`
`wasabi-backend` v klientu 2.6 a upstream podoba opravy MiningFeeRate.

Doplněk 2026-11-15: skip_rounds zrušené úplně jako v upstreamu. Commit „fix(config): reject a scenario
that still asks for skipped rounds“ vypuštěn a `skip_rounds` už není ani mezi odmítanými plochými poli,
takže scénář se `skip_rounds` projde a pole se ignoruje. 225 commitů, force-push MR 41 až 57 s lease
(záloha `backup/mr-split-20261115-cherry/*`), popisy PR #55 až #71 obnovené. Pole zmizelo i z Labu.

## Postup provedení

1. Hotovo: záloha `backup/mr-split-20261115/main`. Worktree nebyl potřeba, `build.py` zapisuje jen
   objekty a větve.
2. Hotovo: větev `stack/mr-split` z `original-rajnoha-branch`: cherry-pick v pořadí z `plan.py`,
   merge č. 183 a 189 jako skutečné merge se stromem z `replay.py`.
3. Hotovo: úpravy z tabulky včetně messages.
4. Hotovo (sekce Stavba): strom vrcholu = strom `main` bez plánu; `git range-diff` proti původním commitům; pytest na
   každém commitu; ruff, mypy a pylint na každém tipu; u vlny 1 import a `compileall`.
5. Hotovo: větve `pr/01-…` až `pr/57-…` na hranicích MR. Nic se nepushuje bez tvého souhlasu.
6. Hotovo 2026-11-15 se souhlasem: větve `pr/01-…` až `pr/57-…` pushnuté do `OndrejMan/coinjoin-emulator`,
   PR #15 (MR 01) až #71 (MR 57), všechny jako draft, název začíná číslem MR („01: …“). Stacky po
   vlnách #72 až #82; vlna 12 má jen jeden PR, a tak je #71 navrchu stacku vlny 11 (#82). Původně:
   push větví, PR ve forku (krátký anglický popis, na konci tvůj odstavec
   o použití AI z PR #7), `GH_REPO=OndrejMan/coinjoin-emulator gh stack link --base <base> …`
   po vlnách. `gh stack link` sám přepíše base každého PR na předchozího člena.
7. CI: na PR běží jen „Static Analysis“ na `ubuntu-latest`, a to od MR 12. Buildy images se
   spouští jen pushem do `main`, takže self-hosted runner se nezatíží.

Do crocs-muni se nic neposílá ani nepushuje.

## Inventář commitů

Číslo je pořadí po prvním rodiči `original-rajnoha-branch..main` bez commitů, které mění jen tento plán
(č. 221 a 222 přibyly po plánu). „Text. závisí na“ je z `git blame` kontextu každého hunku (±1 řádek);
u merge commitů se nepočítá. „Squash do“ je commit, se kterým se v MR spojil.

| # | Hash | Message | +/− | MR | Squash do | Text. závisí na |
|---|---|---|---|---|---|---|
| 1 | 10e6063c | fix(remote): import manager sibling modules | +3 −3 | 01 | – | – |
| 2 | 267a79ed | fix(errors): replace bare exception handlers | +16 −16 | 01 | – | – |
| 3 | ad2fd0b9 | refactor: remove unused local assignments | +1 −6 | 01 | – | – |
| 4 | 5c4f3817 | fix(types): correct inherited type inconsistencies | +5 −4 | 01 | – | – |
| 5 | 858fe602 | feat(errors): add emulator-specific exception types | +14 −0 | 01 | – | – |
| 6 | 416cba2f | fix(bitcoin): raise when block count times out | +12 −7 | 02 | – | – |
| 7 | 1a28ca2d | fix(bitcoin): honor wallet name and creation timeout | +10 −9 | 02 | – | – |
| 8 | 0ef77342 | fix(wasabi): omit unset client environment values | +6 −2 | 02 | – | – |
| 9 | 062280c7 | fix(joinmarket): read max coinjoins from wallet configuration | +3 −1 | 03 | – | – |
| 10 | 2d5e1bbc | fix(joinmarket): fail when a tumbler schedule cannot start | +4 −0 | 03 | – | – |
| 11 | 1dcecfcf | fix(joinmarket): guard node and orderbook client access | +24 −5 | 03 | – | – |
| 12 | 2aa61dfa | fix(remote): preserve helper return values | +2 −0 | 05 | – | – |
| 13 | 9f014fdf | fix(manager): exit through sys.exit | +5 −5 | 04 | – | – |
| 14 | f9a38ae2 | fix(manager): initialize the cleanup driver reference | +4 −0 | 04 | – | – |
| 15 | b85fc325 | fix(engine): fund the distributor with the requested amount | +6 −1 | 04 | – | – |
| 16 | 464de3c0 | fix(engine): reject invalid fund entries | +2 −0 | 04 | – | – |
| 17 | 23145d03 | fix(engine): read fidelity bond flags from wallet configuration | +8 −2 | 04 | – | – |
| 18 | fb20121a | fix(openshift): return the driver endpoint contract | +1 −1 | 04 | – | – |
| 19 | b2ec282c | fix(wasabi): raise when client RPC calls time out | +11 −4 | 02 | – | – |
| 20 | 90cd720a | fix(wasabi): bound coordinator readiness waits | +9 −5 | 02 | – | 2 |
| 21 | f1741abc | fix(runner): default in-cluster mode to false | +1 −1 | 05 | – | – |
| 22 | cc3fd5f8 | fix(remote): pass the selected engine to the scenario runner | +12 −4 | 05 | – | – |
| 23 | f6ae153a | fix(remote): wait for orchestrator rollout | +20 −0 | 05 | – | – |
| 24 | 1c44194b | fix(engine): preserve block export failures | +11 −8 | 04 | – | 6 |
| 25 | e4540284 | fix(joinmarket): honor wallet readiness deadlines | +39 −31 | 03 | – | – |
| 26 | 243f4b08 | feat(cli): add deterministic run identity and timezone | +194 −2 | 06 | – | 6 |
| 27 | f3849eed | feat(manager): write controller completion markers | +77 −3 | 06 | – | 26 |
| 28 | c7fec3e1 | feat(export): write emulator artifacts into a fixed run layout | +55 −2 | 07 | – | 26, 27 |
| 29 | f0ab9a81 | feat(export): write producer label manifests | +193 −7 | 07 | – | 26, 28 |
| 30 | 57d2dca0 | feat(joinmarket): record round lifecycle events | +41 −0 | 08 | – | – |
| 31 | 219518b9 | feat(joinmarket): export round event artifacts | +905 −2 | 08 | – | 26, 29 |
| 32 | 3f7fe6ac | ci(images): publish service container images | +264 −50 | 09 | – | – |
| 33 | 0f794e34 | ci(images): publish the manager image | +50 −0 | 09 | – | – |
| 34 | 394c51be | build: add uv project metadata | +73 −0 | 10 | – | – |
| 35 | fb7bca2b | chore(lint): configure static analysis entry points | +102 −0 | 10 | – | 34 |
| 36 | a3d8dc06 | style: apply automatic Ruff cleanup | +142 −126 | 10 | – | 1, 2, 6, 14, 20, 26, 29, 31 |
| 37 | fdba90cc | test: preserve historical emulator archive contracts | +266 −0 | 18 | – | – |
| 38 | 1603a4ba | ci: add the static analysis workflow | +44 −0 | 12 | – | – |
| 39 | d1cd7eb6 | build: install manager dependencies with uv | +8 −2 | 12 | – | – |
| 40 | 6c5d1c16 | build: lock manager dependencies with uv | +1353 −20 | 12 | – | 26, 34, 38, 39 |
| 41 | f382dfd4 | build: pin the manager image to Python 3.11 | +1 −1 | 12 | – | – |
| 42 | 9f5620f5 | chore(types): enable strict mypy incrementally | +404 −3 | 11 | – | 35 |
| 43 | ce3306db | fix(bitcoin): wait for bitcoind before initializing the regtest chain | +63 −9 | 14 | – | – |
| 44 | d4ccac60 | fix(bitcoin): forward bitcoind arguments | +7 −1 | 14 | – | 43 |
| 45 | 1a9f7488 | fix(irc): disable client hostname resolution | +1 −1 | 34 | – | – |
| 46 | cc4cf531 | fix(image): install kubectl for the target architecture | +3 −1 | 13 | – | – |
| 47 | 1dd097ed | build(image): pin the uv version used to build the manager image | +4 −1 | 12 | – | 39, 41 |
| 48 | ce97cfa5 | fix(image): make the manager sources readable for a non-root UID | +3 −0 | 13 | – | – |
| 49 | 0fe543a0 | fix(image): keep the container build contexts in the manager image | +1 −2 | 13 | – | – |
| 50 | 59e2c626 | build: ignore the setuptools egg-info build debris | +2 −1 | 13 | – | – |
| 51 | f279a0b2 | build(joinmarket): honor the JoinMarket base image argument | +2 −1 | 34 | – | – |
| 52 | 55e701ad | ci: publish the manager image under its deployment name | +5 −2 | 09 | – | 33 |
| 53 | 9148fd78 | fix(bitcoin): send wallet RPC calls to the requested wallet | +25 −1 | 15 | – | – |
| 54 | 0183f410 | fix(bitcoin): surface RPC timeouts instead of returning a sentinel string | +11 −17 | 15 | – | 6, 53 |
| 55 | a9c85632 | fix(bitcoin): create wallets on descriptor-only Bitcoin Core | +78 −6 | 15 | – | 7, 53 |
| 56 | 3bf839c5 | fix(joinmarket): use a fork with lazy regtest mining addresses | +39 −9 | 20 | – | 32 |
| 57 | b46c1814 | fix(joinmarket): isolate Core wallets to avoid concurrent rescans | +162 −21 | 20 | – | 31, 36, 56 |
| 58 | 7ef1e29c | fix(bitcoin): wait for a synchronized node and a usable funding wallet | +243 −12 | 16 | – | 6, 36, 55 |
| 59 | 8c2691da | fix(engine): serialize scenario enums in stored logs | +30 −2 | 07 | – | 26, 27, 29 |
| 60 | 18a4ac20 | fix(config): read and generate nested JoinMarket wallet settings | +163 −73 | 17 | – | 9 |
| 61 | c38902b4 | fix(config): read nested Wasabi wallet settings | +37 −9 | 17 | – | 60 |
| 62 | 242ac67b | test(archives): read archived scenarios as plain JSON | +10 −10 | 18 | 37 | 37 |
| 63 | 11ba3983 | fix(config): reject missing JoinMarket wallet roles before running | +26 −2 | 17 | – | 60, 61 |
| 64 | 011a1ea6 | fix(logs): export the chain tip block | +24 −8 | 07 | – | 24, 26, 28 |
| 65 | ae1f5dfb | fix(funding): keep unpaid invoices scheduled for retry | +5 −2 | 19 | – | – |
| 66 | 1dd5b392 | fix(engine): abort when scenario clients fail to start or answer | +144 −5 | 19 | – | – |
| 67 | 9e851bdf | fix(lifecycle): complete every cleanup step and report the outcome | +82 −19 | 21 | – | 27, 31 |
| 68 | b1405c6d | feat(driver): pass host volumes and container commands through the drivers | +39 −6 | 22 | – | – |
| 69 | 0a251258 | feat(cli): honor pipeline image overrides and Bitcoin node options | +176 −16 | 22 | – | 57 |
| 70 | de1a3a9f | feat(cli): download the raw Bitcoin node data before cleanup | +67 −2 | 22 | – | 26, 67 |
| 71 | ae7b0465 | refactor(cli): build the argument parser in a function | +7 −1 | 21 | – | 67 |
| 72 | 9de1f38e | fix(cli): accept pipeline's --disable-port-forward | +4 −0 | 21 | – | 27 |
| 73 | 8df32e3c | fix(engine): resolve service endpoints consistently for in-cluster runs | +233 −22 | 23 | – | 69 |
| 74 | 69fba310 | fix(docker): address containers by their bridge-network name and published ports | +24 −14 | 23 | – | – |
| 75 | 3225680f | fix(kubernetes): scope cleanup to the resources this emulator labelled | +102 −32 | 25 | – | – |
| 76 | 61974ac4 | fix(kubernetes): require --proxy or --in-cluster to disable port forwarding | +69 −0 | 21 | – | – |
| 77 | 0e779bef | fix(kubernetes): name the quota that rejected a pod | +25 −1 | 25 | – | 36, 68, 75 |
| 78 | 3e60a209 | fix(kubernetes): fail fast when a pod never gets an IP | +49 −9 | 25 | – | 36, 75, 77 |
| 79 | adf7a84c | fix(kubernetes): remove log polling after archive extraction | +0 −39 | 26 | – | 36 |
| 80 | 0506cc14 | test(kubernetes): cover binary archive transfer over exec | +53 −0 | 26 | – | 75, 78 |
| 81 | aa990eb7 | fix(kubernetes): encode downloaded archives as base64 | +18 −17 | 26 | – | 36, 80 |
| 82 | a411f40d | fix(kubernetes): report archive command errors | +68 −3 | 26 | – | 36, 75, 78, 80, 81 |
| 83 | 003b68b1 | fix(kubernetes): bound archive reads and always close the stream | +33 −7 | 26 | – | 78, 81, 82 |
| 84 | e9ffa1f5 | refactor(kubernetes): centralize exec stream opening | +14 −44 | 26 | – | 81 |
| 85 | da746c28 | fix(kubernetes): serialize exec connection setup | +75 −16 | 26 | – | 75, 81, 82, 83, 84 |
| 86 | 0d0e5851 | fix(kubernetes): reject reads from unavailable pods | +36 −0 | 26 | – | 75, 80, 84, 85 |
| 87 | 01b65343 | fix(kubernetes): upload files through checked, chunked commands | +112 −16 | 27 | – | 75, 77, 78, 82, 83, 85, 86 |
| 88 | d676a5c4 | fix(kubernetes): preserve ownership of a shared Bitcoin data directory | +57 −7 | 24 | – | 17, 68, 69, 73 |
| 89 | 7c196c52 | feat(kubernetes): make the image pull policy configurable | +15 −1 | 27 | – | 87 |
| 90 | add82493 | fix(docker): retain containers for artifact collection | +15 −3 | 28 | – | 74 |
| 91 | ce0e670f | fix(docker): pause running containers during archive download | +38 −1 | 28 | – | 90 |
| 92 | 1a18d585 | fix(docker): report artifact download failures | +14 −2 | 28 | – | 2, 74, 90, 91 |
| 93 | da541b35 | fix(podman): use the native API for images and container operations | +116 −14 | 29 | – | 36 |
| 94 | 7914f793 | fix(podman): configure the network, mounts and published ports | +64 −5 | 29 | – | 36, 93 |
| 95 | 95261c79 | fix(podman): retain containers until explicit cleanup | +50 −8 | 29 | – | 93, 94 |
| 96 | 57e32637 | refactor(drivers): share cleanup image markers | +37 −12 | 29 | – | 36, 74, 90, 92, 93, 95 |
| 97 | 6f8646f6 | fix(podman): fail when artifact download fails | +14 −2 | 29 | – | 2, 36, 95 |
| 98 | 0781736f | fix(driver): reserve the Wasabi service ports in every container | +25 −3 | 30 | – | 36, 68, 77, 87, 89, 93, 94, 96 |
| 99 | 2c052d2e | fix(kubernetes): retry without port sysctl after API rejection | +48 −1 | 30 | – | 68, 77, 82, 98 |
| 100 | 585d6583 | refactor(kubernetes): extract pod creation retry | +16 −12 | 30 | – | 68, 77, 78, 99 |
| 101 | 6de2dd56 | fix(kubernetes): retry after kubelet rejects port sysctl | +28 −0 | 30 | – | 78, 99 |
| 102 | 3711b85b | fix(joinmarket): reject a wallet that stays locked | +43 −5 | 35 | – | – |
| 103 | 770cd729 | fix(joinmarket): interpolate the client name in the completion log | +2 −2 | 35 | – | – |
| 104 | d2a0bb57 | fix(joinmarket): give a role-only scenario its legacy default offers | +56 −1 | 35 | – | – |
| 105 | a9048d2e | fix(joinmarket): require a started maker and taker before funding | +38 −0 | 35 | – | 56, 57 |
| 106 | e16eeb46 | refactor(joinmarket): share destination-output matching between live and export | +222 −22 | 36 | – | 31 |
| 107 | ea81d83a | fix(joinmarket): distinguish destination conflicts with explicit statuses | +131 −19 | 36 | – | 31, 106 |
| 108 | 7fcb4cf8 | fix(joinmarket): count only CoinJoin rounds that were actually mined | +90 −5 | 37 | – | 31, 57 |
| 109 | df9baaaa | fix(joinmarket): stop takers from starting attempts past the round limit | +31 −0 | 37 | – | 108 |
| 110 | 1a6d34df | feat(joinmarket): make taker timeout configurable | +75 −8 | 38 | – | 25, 60, 63 |
| 111 | 8bb5e6d5 | refactor(joinmarket): share taker status transition | +9 −15 | 38 | – | – |
| 112 | e7ba9e07 | fix(joinmarket): hold a taker until its previous attempt is mined | +112 −2 | 38 | – | 111 |
| 113 | 9fe04bfc | fix(joinmarket): count taker CoinJoins only once mined | +56 −9 | 38 | – | 111, 112 |
| 114 | 93624e1e | fix(joinmarket): settle pending attempts before pausing | +15 −4 | 38 | – | 112, 113 |
| 115 | 4c0fae8e | fix(joinmarket): mine confirmations for the last broadcast before capture | +2 −1 | 37 | – | – |
| 116 | e1d8b34a | fix(joinmarket): mark tumbler label evidence as incomplete | +9 −1 | 37 | – | 31 |
| 117 | 067ece0f | fix(joinmarket): export every derived wallet address | +68 −31 | 39 | – | 36, 56 |
| 118 | 2f4e1518 | fix(joinmarket): preserve key metadata in wallet export | +84 −6 | 39 | – | 36, 117 |
| 119 | 0b4ddc1d | fix(joinmarket): require a block limit for round-limited tumblers | +30 −0 | 37 | – | 63 |
| 120 | b8b6179a | fix(joinmarket): make watcher termination explicit | +6 −9 | 34 | – | 57 |
| 121 | 44a99072 | feat(driver): accept build arguments for image builds | +77 −10 | 34 | – | 69, 74, 93 |
| 122 | 450a96b8 | fix(build): build the vendored JoinMarket base locally and use it | +73 −1 | 34 | – | 49, 57 |
| 123 | f0a9d2ca | test(config): collect tests only from the tests directory | +1 −0 | 10 | – | 34 |
| 124 | 21c1f174 | chore(lint): exclude the vendored JoinMarket tree from ruff | +3 −0 | 20 | – | 35 |
| 125 | f77ed099 | feat(bitcoin): make the initial regtest block count configurable | +18 −0 | 24 | – | 69, 88 |
| 126 | d0b807db | fix(bitcoin): target the regtest funding wallet in fee-history mining | +22 −9 | 14 | – | 43 |
| 127 | 78d9dc15 | fix(bitcoin): allow slow funding and mining RPCs | +73 −4 | 16 | – | 54 |
| 128 | bf7fb946 | fix(bitcoin): judge mining by the block hashes generatetoaddress returned | +31 −5 | 16 | – | 127 |
| 129 | 3851a78d | fix(funding): retain unpaid batches after partial failure | +22 −2 | 19 | – | 36, 66 |
| 130 | 10060e55 | fix(wasabi): bound the backend and client readiness waits | +56 −14 | 40 | – | 2, 36 |
| 131 | 76004b42 | fix(wasabi): count only successfully broadcast CoinJoin rounds | +57 −15 | 41 | – | 29, 36 |
| 132 | 5f41b504 | fix(wasabi): stop at the requested CoinJoin round limit | +20 −2 | 41 | – | 131 |
| 133 | c8d3882e | fix(wasabi): mine confirmations for the last broadcast before capture | +14 −0 | 41 | – | 36, 131, 132 |
| 134 | 2954c4e8 | fix(wasabi): stop mixing before settlement mining | +21 −8 | 41 | – | 131, 132, 133 |
| 135 | 34ea6079 | feat(wasabi): make the distributor startup timeout configurable | +65 −6 | 42 | – | 22, 26, 27, 36, 67, 71, 72, 76, 131, 133 |
| 136 | d6446e11 | feat(driver): expose container logs | +12 −0 | 31 | – | – |
| 137 | e3fb6a87 | fix(wasabi): retry a transient coordinator startup failure | +114 −23 | 42 | – | 73, 131, 135 |
| 138 | f4e1c50c | refactor(wasabi): pass the coordinator endpoint to the split distributor | +26 −4 | 42 | – | 137 |
| 139 | 52dd598b | fix(wasabi): retry getnewaddress with backoff | +62 −2 | 43 | – | 19 |
| 140 | 4a4ec129 | feat(driver): expose a best-effort container state | +22 −0 | 31 | – | 84, 86 |
| 141 | 8d375904 | fix(wasabi): name the dead client and its container state on connection refused | +82 −1 | 43 | – | 29 |
| 142 | 5b99fe61 | fix(wasabi): use the canonical source repository for 2.6.0 images | +3 −3 | 44 | – | – |
| 143 | 99858aa8 | fix(wasabi): disable NuGet audit in pinned 2.6.0 builds | +12 −3 | 44 | – | – |
| 144 | 376a73fc | build(wasabi): shallow-clone the 2.6.0 source tag | +3 −6 | 44 | – | 142 |
| 145 | f45c45dc | fix(kubernetes): scope cleanup to this run's own resources | +22 −2 | 25 | – | 75, 77 |
| 146 | 9c30e701 | fix(kubernetes): wait for a stopped pod to disappear before returning | +56 −1 | 33 | – | 82, 85, 87, 99, 101 |
| 147 | d3f9dcc1 | fix(remote): write valid simulation status JSON | +1 −1 | 47 | – | – |
| 148 | d929009c | fix(remote): record the manager's exit status | +8 −1 | 47 | – | 36 |
| 149 | bdec11c0 | fix(runner): merge the manager's stderr into stdout | +3 −3 | 48 | – | – |
| 150 | 1ed51741 | fix(runner): stream stdout and stderr concurrently | +156 −7 | 48 | 149 | 149 |
| 151 | 11d48095 | fix(runner): create the logs directory before saving results | +1 −0 | 48 | – | – |
| 152 | 405cf075 | fix(remote): apply the manager image override without rewriting its manifest | +102 −14 | 47 | – | 34 |
| 153 | b4a320aa | fix(remote): fail when the orchestrator deployment never becomes ready | +2 −2 | 47 | – | – |
| 154 | f8c0d033 | fix(genscen): escape the percent signs in the generator help | +14 −6 | 48 | – | 135 |
| 155 | 4405ee2b | fix(docker): report container memory resource usage | +62 −0 | 31 | – | 36, 96, 136 |
| 156 | 832c9323 | test(joinmarket): cover late confirmations and export conflicts | +153 −24 | 36 | – | 31, 106, 107 |
| 157 | 67dfb219 | fix(wasabi): honor configured skipped rounds (vypuštěn) | +63 −7 | 41 | – | 73, 131, 132, 134 |
| 158 | 2864e101 | fix(podman): pass the requested namespace | +27 −1 | 32 | – | 76 |
| 159 | 913f5111 | fix(drivers): scope local cleanup by ownership | +123 −50 | 32 | – | 36, 68, 74, 76, 90, 92, 93, 94, 95, 96, 97, 98, 155, 158 |
| 160 | ac5bd457 | test(archives): replay historical archives with the current contract | +100 −14 | 18 | – | 37, 62 |
| 161 | 0b7da1cc | fix(wasabi): accept empty coordinator readiness responses | +33 −1 | 40 | – | – |
| 162 | 592966e0 | fix(wasabi): abort after exhausted state polling retries | +66 −2 | 41 | – | 134 |
| 163 | 79de9013 | fix(joinmarket): preserve events without destination evidence | +42 −5 | 36 | – | 31, 106, 107, 156 |
| 164 | 7fdf9cec | fix(joinmarket): retain execution status during chain reconciliation | +67 −7 | 36 | – | 30, 31, 106, 107, 156, 163 |
| 165 | 15c0ea2e | refactor(joinmarket): extract taker attempt helpers | +33 −28 | 38 | – | 30, 112, 113 |
| 166 | 0c439d1e | fix(joinmarket): record a round before its start RPC is answered | +121 −15 | 38 | – | 30, 31, 102, 106, 107, 112, 156, 164, 165 |
| 167 | 82093955 | feat(driver): add pause and unpause to freeze a container | +113 −8 | 54 | – | 81, 87, 91, 97, 159 |
| 168 | 4f6ccf73 | fix(cli): copy the Bitcoin datadir as a flushed, frozen snapshot | +222 −5 | 54 | – | 14, 36, 58, 67, 70, 127 |
| 169 | edf304f8 | fix(podman): include stderr in container logs | +15 −1 | 31 | – | 93, 136 |
| 170 | 383df05f | ci(joinmarket): update clientserver submodule to CI commit | +1 −1 | 20 | – | – |
| 171 | e1b77e52 | fix(ci): publish btc-node for amd64 only | +1 −1 | 09 | – | 32 |
| 172 | 00a4091e | fix(joinmarket): start the scenario block clock after the warm-up blocks | +61 −8 | 35 | – | – |
| 173 | d9b15731 | chore(vendor): bump joinmarket-clientserver to 45b2e1c | +1 −1 | 20 | 170 | – |
| 174 | ab66d2d8 | fix(kubernetes): open exec streams on a dedicated API client | +38 −4 | 26 | – | 2, 85, 86 |
| 175 | 832c7aef | fix(wasabi): download client logs from the client data directory | +22 −1 | 43 | – | 131, 133 |
| 176 | 2612497d | fix(joinmarket): tell jmwalletd state 401s from auth failures and probe startup quietly | +135 −14 | 35 | – | 102 |
| 177 | fdae4c42 | fix(wasabi): wait for WalletState.Started before using a wallet | +67 −6 | 40 | – | 2, 36, 130 |
| 178 | add68c85 | chore(vendor): pick up the joinmarket-clientserver dust-offer fix | +1 −1 | 20 | 170 | – |
| 179 | abf09725 | fix(driver): warn when host ports are unreserved | +89 −3 | 32 | – | 36, 74, 92, 93, 98, 155, 159 |
| 180 | 59d544c5 | chore(vendor): update JoinMarket clientserver | +1 −1 | 20 | 170 | – |
| 181 | 8ce5c701 | fix(kubernetes): tie emulation resources to controller pod | +60 −2 | 33 | – | 75, 145 |
| 182 | 047a50dc | fix(wasabi): retry key RPCs hit by the Wasabi key-cache race | +61 −1 | 43 | – | 19, 139 |
| 183 | 4f35491f | chore(upstream): merge crocs-muni mining fee rate support (merge) | +189 −8 | 45 | – | – |
| 184 | 98c3daaa | fix(wasabi): decode an absent MiningFeeRate as null in the 2.6.0 patches (vypuštěn) | +2 −2 | 45 | – | – |
| 185 | 8184ee4e | fix(kubernetes): wait for running containers before uploads | +80 −3 | 27 | – | 86, 87 |
| 186 | 3071e1c6 | fix(wasabi): synchronize coordinator configuration startup | +249 −37 | 45 | – | 137, 138, 183 |
| 187 | 7c9ce3e7 | fix(wasabi): use Debian snapshots for legacy client images | +28 −8 | 44 | – | – |
| 188 | 70dbafe9 | fix(wasabi): remove x86-only debug step from legacy images | +0 −8 | 44 | – | – |
| 189 | f2891a1d | Merge crocs-muni/coinjoin-emulator main (merge) | +13 −0 | 49 | – | – |
| 190 | 3094e8c9 | feat(remote): unified remote CLI for in-cluster runs (Rajnoha) | +361 −0 | 50 | – | 42, 50 |
| 191 | 642c7fab | fix(kubernetes): spool downloaded archives to disk and bound the log download pool (Rajnoha) | +78 −24 | 50 | – | 36, 69, 75, 78, 81, 82, 83, 85 |
| 192 | d0dbe49a | fix(runner): default the shadowsocks config relative to the script (Rajnoha) | +4 −2 | 50 | – | 150 |
| 193 | 678001ce | feat(kubernetes): keep the orchestrator workspace and run archives on a PVC (Rajnoha) | +58 −5 | 50 | – | 152 |
| 194 | 06e9817e | refactor(configuration): extract the bool-rejecting integer check | +6 −8 | 51 | – | 110 |
| 195 | d374367e | feat(configuration): parse Wasabi postmix spend schedules | +108 −0 | 51 | – | 61, 63, 119, 194 |
| 196 | fcdd121a | feat(wasabi): spend mixed coins without change | +129 −0 | 52 | – | 130, 182 |
| 197 | 78bd1c6c | refactor(engine): add hooks for engine wallet schedules and records | +9 −0 | 52 | – | – |
| 198 | 53c9a49b | feat(wasabi): record the postmix spend schedule | +110 −0 | 52 | – | 36, 134, 175, 196 |
| 199 | 4abcc065 | feat(wasabi): send scheduled postmix spends once due | +148 −4 | 52 | – | 61, 132, 162, 196, 198 |
| 200 | ea6a6116 | feat(configuration): parse scenario metadata | +43 −2 | 51 | – | 61 |
| 201 | ff26f35b | fix(postmix): keep mixing until the mixed coins cover a spend | +24 −1 | 52 | – | 196, 199 |
| 202 | 67d063ab | fix(driver): give uploaded files to the container user | +126 −12 | 32 | – | 74, 93, 96, 97, 98, 179 |
| 203 | 6c69bc06 | fix(wasabi-client): keep the node's reason for a rejected broadcast | +36 −0 | 46 | – | – |
| 204 | b06d252c | fix(postmix): skip coins the node already sees spent | +89 −16 | 52 | – | 128, 130, 196, 198, 199, 201 |
| 205 | 07cca7e5 | fix(kubernetes): isolate concurrent runs in shared namespaces | +142 −27 | 55 | – | 36, 68, 75, 78, 82, 84, 85, 86, 87, 89, 100, 101, 136, 140, 145, 146, 167, 181, 185, 191 |
| 206 | 9af48092 | fix(wasabi): ignore unsupported privacy settings on 2.6 | +52 −1 | 41 | – | 157 |
| 207 | 2dc18ae3 | refactor(wasabi): extract anon-score coin selection | +15 −7 | 53 | – | 196, 201 |
| 208 | b378a910 | refactor(wasabi): separate all-coin selection | +9 −3 | 53 | – | 196, 207 |
| 209 | 9f8ddf1b | feat(postmix): let a spend pick coins by amount | +115 −15 | 53 | – | 61, 194, 195, 196, 198, 199, 204, 207, 208 |
| 210 | a4cbbcf4 | feat(run-log): keep the manager output in the run artifacts | +172 −0 | 56 | – | 6, 26, 27, 28, 31, 36, 64, 135 |
| 211 | 5918b6ed | feat(kubernetes): explain pending and exited pods in their state | +61 −4 | 55 | – | 68, 140, 205 |
| 212 | fb64cceb | feat(manager): report infrastructure pod states when a run fails | +100 −0 | 56 | – | 67, 141 |
| 213 | e829818f | fix(wasabi): test block filters against a snapshot of the wallet keys | +18 −0 | 46 | – | 203 |
| 214 | a9d64f4e | fix(run-log): preserve manager output when artifact export fails | +63 −36 | 56 | – | 24, 29, 64, 191, 197, 210 |
| 215 | 4ad96ba6 | fix(wasabi): wait for settlement before sweeping all mixed coins | +112 −0 | 53 | – | 182, 196, 199, 201, 204, 207, 209 |
| 216 | bca825cc | WIP fix(joinmarket): honor wallet start and stop schedules | +139 −14 | 57 | – | 108, 112, 114 |
| 217 | ee3b38fe | WIP fix(joinmarket): initialize tumbler schedule files without mutating options | +23 −2 | 57 | – | 216 |
| 218 | c15f45f0 | WIP feat(joinmarket): add scheduled postmix withdrawals | +502 −25 | 57 | – | 9, 31, 36, 60, 61, 108, 109, 195, 196, 198, 199, 209, 215 |
| 219 | 5e8a767d | fix(joinmarket): export daemon logs for coinjoin analysis | +83 −0 | 39 | – | 107, 109, 218 |
| 220 | 02b20e47 | fix(wasabi): wait for the backend data directory before uploading its config | +53 −10 | 45 | – | 135, 137, 186 |
| 221 | 05e16b5b | fix(kubernetes): delete a stopped client's service even when its pod is gone | +24 −8 | 33 | – | 2, 146 |
| 222 | d061369a | fix(wasabi): stop watching the configuration in the 2.6.0 images | +10 −0 | 44 | – | – |
| 301 | dde60b54 | Fix config loading with new format (crocs-muni, cherry-pick) | +13 −12 | 17 | – | – |
| 302 | afdf9e0d | Fix wasabi client data path (crocs-muni, cherry-pick) | +1 −1 | 43 | – | – |
| 303 | 6c595423 | Fix round counter restarts when coordinator poll fails (crocs-muni, cherry-pick) | +6 −6 | 41 | – | – |
| 304 | 87a2c934 | Improve container cleanup (crocs-muni, cherry-pick) | +25 −20 | 21 | – | – |
| 305 | b93c1287 | Fix wallet funds addressing with failed clients (crocs-muni, cherry-pick) | +22 −30 | 19 | – | – |
| 306 | 194bf146 | Fix failure with null mining fee rate (crocs-muni, cherry-pick) | +3 −3 | 45 | – | – |
| 307 | 12528c49 | Unify backend naming in log collection (crocs-muni, cherry-pick) | +16 −24 | 43 | – | – |
| 308 | 2a1f09ed | Drop skip_rounds (crocs-muni, cherry-pick) | +24 −91 | 41 | – | – |
