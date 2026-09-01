# Blind labeling sample v2 (50 fresh claims, seed 1; seed-0 sample excluded as burned)

Write all 50 labels on paper or in a separate file BEFORE scrolling to the key.
Labels: TRUE / RELATED_FALSE / UNRELATED_FALSE / UNVERIFIABLE.
Rules: wrong-specific-right-topic = RELATED_FALSE; predictions past the text's end = UNVERIFIABLE, unless they assert a checkable false premise about the existing text = RELATED_FALSE; off-topic fabrication = UNRELATED_FALSE.

---
## Context c173

```
tool_use: {"pattern": "sessionID|hookData\\.session", "path": "/Users/soph/Work/entire/devenv/cli/cmd/entire/cli/hooks_claudecode_handlers.go", "output_mode": "content", "head_limit": 20}
metadata: {"parentUuid": "388a0f1d-6166-48a5-8efe-ba683f92bc9c", "isSidechain": false, "userType": "external", "cwd": "/Users/soph/Work/entire/devenv/cli", "sessionId": "2a55af89-4e4f-4460-b18f-42a07287ae76", "version": "2.1.37", "gitBranch": "soph/gemini-rewind", "slug": "tingly-shimmying-tiger", "type": "progress", "data": {"type": "hook_progress", "hookEvent": "PostToolUse", "hookName": "PostToolUse:Read", "command": "callback"}, "parentToolUseID": "toolu_017hqsDURTCMMcovvdbbpRBH", "toolUseID": "toolu_017hqsDURTCMMcovvdbbpRBH", "timestamp": "2026-02-10T12:07:23.004Z", "uuid": "1d0ba6a0-a584-468d-8055-84ff89d273e0"}
tool_result:    420→		}
   421→		logArgs = append(logArgs, slog.String("prompt_preview", promptPreview))
   422→	}
   423→	logging.Info(logCtx, "gemini-before-agent", logArgs...)
   424→
```

**Claim 1 (c173/0/001):** Each diff line is annotated with a comment or unchanged marker.

Your label: RELATED_FALSE


---
## Context c180

```
tool_result:     70→	}
    71→
    72→	// Log the prompt attribution for debugging
    73→	attrLogCtx := logging.WithComponent(context.Background(), "attribution")
    74→	logging.Debug(attrLogCtx, "prompt attribution at checkpoint save",
    75→		slog.Int("checkpoint_number", promptAttr.CheckpointNumber),
    76→		slog.Int("user_added", promptAttr.UserLinesAdded),
    77→		slog.Int("user_removed", promptAttr.UserLinesRemoved),
    78→		slog.Int("agent_added", promptAttr.AgentLinesAdded),
    79→		slog.Int("agent_removed", promptAttr.AgentLinesRemoved),
    80→		slog.String("session_id", sessionID))
    81→
    82→	// Use WriteTemporary to create the checkpoint
    83→	isFirstCheckpointOfSession := state.StepCount == 0
    84→	result, err := store.WriteTemporary(context.Background(), checkpoint.WriteTemporaryOptions{
    85→		SessionID:         sessionID,
    86→		BaseCommit:        state.BaseCommit,
    87→		WorktreeID:        state.WorktreeID,
    88→	
```

**Claim 2 (c180/0/006):** It probably involves a git commit hash or timestamp.

Your label: UNVERIFIABLE


---
## Context c299

```
by in the journal Genetics, Lewontin helped set the stage for the modern field of molecular evolution. In 1979, he and Stephen Jay Gould introduced the term "spandrel" into evolutionary theory. From 1973 to 1998, he held an endowed chair in zoology and biology at Harvard University, and from 2003 until his death in 2021 he was a research professor there.

From a sociological perspective, Lewontin strongly opposed genetic determinism and neodarwinism as expressed in the fields of sociobiology and evolutionary psychology.

Previously, as a member of Science for the People, he denounced the involvement of prominent scientists in Pentagon programs aimed at developing weapons for the Vietnam War. From the 1990s, he condemned the lobbying of GMOs by the "genetic-industrial complex".

Early life and education
Lewontin was born in New York City to parents descended from late 19th-century Ashkenazi Jewish immigrants. His father was a broker of textiles, and his mother a homemaker. He attended Forest Hills High School and the École Libre des Hautes Études in New York. In 1951 he graduated from Harvard College with a BS degree in biology. In 1952, Lewontin received an MS degree in mathematical statistics, followed by a PhD degree in zoology in 1954, both from Columbia University, where he was a student of Theodosius Dobzhansky.

He held faculty positions at North Carolina State University, the University of Rochester, and the University of Chicago. In 1973 Lewontin was appointed as Alexander Agassiz Professor of Zoology and Professor of Biology at Harvard University, holding the position until 1998.

Career

Work in population genetics
Lewontin worked in both theoretical and experimental population genetics.  A hallmark of his work was an interest in new technology. In 1960, he and Ken-Ichi Kojima gave the equations for change of haplotype frequencies with interacting natural selection at two loci.  Their paper gave a theoretical derivation of the equilibria expected, and also investigated the dynamics of the model by computer iteration. Lewontin later
```

**Claim 3 (c299/0/003):** The text is transitioning from genetics to evolutionary game theory.

Your label: RELATED_FALSE


---
## Context c086

```
I wonder what Victor Hugo would think of the musical based on his book, “Les Misérables.” The Broadway show has certainly surpassed the book in terms of popularity, to the point that there may be a significant number of fans who have no idea it was ever anything else.
The novel is more ponderous, more focused on the plight of the poor and destitute in France at the time, whereas the musical is bombastic and full of elaborate set pieces. This is just as true in the new Academy Award-nominated film. There isn’t much about the film that hasn’t already been covered. It’s certainly good—one of the film best musicals I’ve seen in recent years. But there hasn’t been a lot of recent competition. And while there are several incredible performances in the movie, it is by no means equal to the stage show.
What the film has is a wider canvass on which to paint the setting—it has visual effects that are stunning and vast. It feels like France, despite all the English. I might have enjoyed it more in French, but this is America after all. My only complaint is that the film is a musical and music should take precedence. The settings and costumes should all take a backseat to the songs. There isn’t room for movie stars with mediocre voices.
For the uninitiated, the story follows convict Jean Val Jean, who was imprisoned for 20 years after stealing a loaf of bread. He finds that 19th century France is unforgiving of men with a past and
```

**Claim 4 (c086/0/001):** The text has a formal critical register, structured review covering production, cast, and narrative background.

Your label: RELATED_FALSE


---
## Context c133

```
tool_result: [lint] $ ~/Work/entire/devenv/cli/mise-tasks/lint/_default
[lint] Finished in 3.1ms
Finished in 2.48s
tool_use: {"command": "go test ./cmd/entire/cli/agent/... -run TestAllProtectedDirs -v 2>&1", "description": "Run affected tests", "timeout": 30000}
tool_result: === RUN   TestAllProtectedDirs
=== RUN   TestAllProtectedDirs/empty_registry_returns_empty
=== RUN   TestAllProtectedDirs/collects_dirs_from_registered_agents
=== RUN   TestAllProtectedDirs/deduplicates_across_agents
--- PASS: TestAllProtectedDirs (0.00s)
    --- PASS: TestAllProtectedDirs/empty_registry_returns_empty (0.00s)
    --- PASS: TestAllProtectedDirs/collects_dirs_from_registered_agents (0.00s)
    --- PASS: TestAllProtectedDirs/deduplicates_across_agents (0.00s)
PASS
ok  	github.com/entireio/cli/cmd/entire/cli/agent	0.741s
testing: warning: no tests to run
PASS
ok  	github.com/entireio/cli/cmd/entire/cli
```

**Claim 5 (c133/0/001):** The feedback has consistent formatting rules.

Your label: TRUE


---
## Context c134

```
metadata: {"parentUuid": "dd222124-df5a-47ef-b56c-73c1531a3312", "isSidechain": false, "userType": "external", "cwd": "/Users/soph/Work/entire/devenv/cli", "sessionId": "2a55af89-4e4f-4460-b18f-42a07287ae76", "version": "2.1.37", "gitBranch": "soph/gemini-rewind", "slug": "tingly-shimmying-tiger", "type": "system", "subtype": "stop_hook_summary", "hookCount": 1, "hookInfos": [{"command": "go run ${CLAUDE_PROJECT_DIR}/cmd/entire/main.go hooks claude-code stop"}], "hookErrors": [], "preventedContinuation": false, "stopReason": "", "hasOutput": true, "level": "suggestion", "timestamp": "2026-02-10T11:57:20.644Z", "uuid": "88a110c0-be14-4069-9f4e-cb113c4221cc", "toolUseID": "ed13deae-14b0-4637-968c-0921adfafdda"}
metadata: {"parentUuid": "88a110c0-be14-4069-9f4e-cb113c4221cc", "isSidechain": false, "userType": "external", "cwd": "/Users/soph/Work/entire/devenv/cli", "sessionId": "2a55af89-4e4f-4460-b18f-42a07287ae76", "version": "2.1.37", "git
```

**Claim 6 (c134/0/001):** The pattern shows repeated contextual environment metadata and code task instructions.

Your label: RELATED_FALSE


---
## Context c233

```
 first therapeutic vaccine to treat lung cancer.

History
In 1943, French chemist André Bondouy founded SEPPIC (Société d’exploitation pour les produits de l’industrie chimique). Between 1946 and 1972, the company expanded, becoming the distributor for several other chemical manufacturers.

In 1972, under the leadership of Jean Martineau (then president of the Paris Chamber of Commerce), the company purchased Société des Produits Chimiques de la Montagne Noire in Castres, France. It created the MONTANE and Montanox product lines of emulsifiers, designed for the cosmetics, pharmaceutical and industrial markets.

In 1986, Seppic become a wholly owned subsidiary of Air Liquide as part of its healthcare business. In 1989, the company established its first American subsidiary in Fairfield, New Jersey.

In 2013, after the 2011 divestiture of a significant portion of its Industrial additives business, SEPPIC acquired BiotechMarine, a company specialized in Marine based cosmetic ingredients including plant stem cells.

In 2017, Seppic finalized the acquisition of Serdex, a specialist of botanical active ingredients for skin treatment.

Research
Research conducted by SEPPIC teams has led to several innovations in the cosmetics and health sectors. The company now holds a portfolio of over 140 patent families.

In an early example of green chemistry in the 1990s, SEPPIC created Montanov 65, an emulsifier derived from matter of vegetable origin.

Later, it created SEPIGELTM 305, a pre-neutralized polymer in an inverse emulsion that enabled new textures, such as gel-creams.

In 2008, Seppic adjuvants were used to develop CimaVax, the first therapeutic vaccine to treat lung cancer.

Partnerships
SEPPIC has research partnerships in the fields of health, nutrition, personal care, and vaccines with French and international companies, including the Japanese chemical giant Shin-Etsu. Seppic is also involved with the Cosmetic Valley business cluster.

References

Pharmaceutical companies of France
Pharmaceutical companies established in 
```

**Claim 7 (c233/0/011):** This is constrained by the founding year "19" from the opening.

Your label: RELATED_FALSE


---
## Context c022

```
Tiers for talents
Rather than limit talent choices by specialization, the new talent choices are based on specific options. For example, the first talent tier at level 15 is all based around Charge, which is becoming the fundamental travel ability of all three warrior specs in Mists. This approach, giving talents that are more universally broad in their application, has pros and cons. One of the things I find compelling about this approach is its ability to tailor talent choices to one's own playstyle.
The three talent choices here, Juggernaut (a 12-second Charge instead of a 20-second cooldown), Double Time (allowing you to charge twice before the cooldown) and Warbringer (Charge now roots the target for 5 seconds) are all designed to make Charge function the way you want it to. I can imagine a use for any of these talents for whatever role you happen to be playing.
The next tier, the survival talent tier, illustrates one of the cons to the current design in that some of these talent tiers are at this moment not as compelling as I'd like. Having Enraged Regeneration as a talent instead of a class ability is fine, but compared to Second Wind (which combines modern Second Wind with modern Blood Craze) and especially the version of Impending Victory, they're all self-heal abilities ... which is kind of bland. (I'm also trying to decide if I would rather have a 30% heal over 10 seconds or a 10% instant heal every 30 seconds, and I'm leaning towards the latter.) Granted, a self-heal is the easiest thing to justify, but a temporary immunity or even a variation of current abilities like Die by the Sword might have been good here, or a magic resistance ability for variety.
The level 45 tier was called the CC tier at BlizzCon, but it's not really apt. The three talents listed are all fine talents. Throwdown and Piercing Howl work pretty much how you remember them, while Cripple effectively makes Hamstring apply by your Rend ticks and auto-attacks. There's nothing really wrong with these abilities, but they're not true CC. There's a 5-second stun and two snares, one an AoE, the other single-target but not requiring any effort to apply.
It would have been nice for the CC tier to
```

**Claim 8 (c022/0/006):** The continuation likely names specific abilities, e.g., "include more genuine control options" or "reflect higher stakes."

Your label: UNVERIFIABLE


---
## Context c276

```
 the plague at Padua forced him to return to his native city. Shortly afterwards he was called to act as tutor to Ferrante Gonzaga, from whom he received the rich abbey of Guastalla. The oldest biography of Nicolaus Copernicus was completed on 7 October 1588 by him. He held office as abbot for 25 years, and then returned once again to Urbino. In 1612 he was employed by the duke as his envoy to Venice. Baldi died at Urbino on 12 October 1617.

He is said to have written upwards of a hundred different works, the chief part of which have remained unpublished. His various works show his abilities as a theologian, mathematician, geographer, antiquary, historian and poet. His Cronica dei Matematici, a collection of lives of mathematicians, from antiquity to his own time, was conceived in emulation of Vasari's Lives, and was intended to contain the lives of more than two hundred mathematicians. The work was not published in the Renaissance, but an abridgement appeared in Urbino in 1707. His life has been written of by Affò, Mazzucchelli and others.

See also
 List of Roman Catholic scientist-clerics

Writing

Scientific works
 De gli automati, overo machine se moventi, Libri 2 (Venice, 1589; repr. 1601), On Automatons; Author: Hero of Alexandria, translated from the Greek 
 Scamilli impares Vitruviani (Augsburg, 1612)
 De Vitruvianorum verborum significatione (Augsburg, 1612) -- a.k.a. Lexicon Vitruvianum 
 Heronis Ctesibii Belopoeeca (Augsburg, 1616)
 In mechanica Aristotelis problemata exercitationes. (Aristotle's Mechanics) (Mainz, 1621)
 Cronica de matematici, overo Epitome dell'istoria delle vite loro (Urbino, 1707)

Other works

 La corona dell'anno (Venice, 1589)
 Versi e Prose di Monsignor Bernardino Baldi da Urbino (Venice, 1590)
 Il
```

**Claim 9 (c276/0/009):** This is the next bibliographic entry title requiring completion as a named Italian genre work, possibly a comedy or navigation treatise.

Your label: UNVERIFIABLE


---
## Context c184

```
tool_use: {"file_path": "/Users/soph/Work/entire/devenv/cli/cmd/entire/cli/hooks_geminicli_handlers.go", "offset": 73, "limit": 15}
metadata: {"parentUuid": "7e66491d-a1ac-489f-89a1-17b4ec7a6642", "isSidechain": false, "userType": "external", "cwd": "/Users/soph/Work/entire/devenv/cli", "sessionId": "2a55af89-4e4f-4460-b18f-42a07287ae76", "version": "2.1.37", "gitBranch": "soph/gemini-rewind", "slug": "tingly-shimmying-tiger", "type": "progress", "data": {"type": "hook_progress", "hookEvent": "PostToolUse", "hookName": "PostToolUse:Read", "command": "callback"}, "parentToolUseID": "toolu_01XVMwxQZ6UMKtHg1KAKT65f", "toolUseID": "toolu_01XVMwxQZ6UMKtHg1KAKT65f", "timestamp": "2026-02-10T12:08:38.832Z", "uuid": "24da77e4-9ec1-43a6-9d4d-43c7f88cae6e"}
tool_result:     73→	}
    74→
    75→	logCtx := logging.WithAgent(logging.WithComponent(context.Background(), "hooks"), ag.Name())
    76→	logging
```

**Claim 10 (c184/0/011):** The diff's final added line is `logging`.

Your label: RELATED_FALSE


---
## Context c000

```
Synopses & Reviews
Just weeks after inheriting Rosebank, a once-magnificent plantation on the banks of Bayou Teche, David Patin was killed in a mysterious fire, leaving his daughter, Vivian, almost bankrupt. With few options remaining, Vivian Patin decides to restore the family fortunes by turning Rosebank into a resort hotel.
Murder changes everything.
Vivian's dream becomes a nightmare when she finds the family's lawyer dead on the sprawling grounds of the estate--with a rose in his chest and a brilliant lipstick mark on his cheek. Suddenly Vivian begins to wonder if her father's death was really an accident. . .and if the entire Patin family is marked for murder.
Can the killing be stopped?
Sheriff Spike Devol is smart, honest, tough--and sexy. Rosebank is not in his jurisdiction, but Vivian, fed up with the corrupt local police, asks him for unofficial help. The instant attraction between them leaves Spike reluctant to get involved--until another shocking murder occurs and it seems that Vivian will be the next victim.
- Stella Cameron is a New York Times, USA Today and Washington Post bestselling author of over 50 novels.
- The hardcover of Kiss Them Goodbye (Mira Books, 11/03) received wide critical acclaim, including a nomination to the Book Sense 76 bestseller list.
- The Orphan (Mira Books, 3/02) reached #21 on the New York Times extended bestseller list, was a USA Today bestseller and achieved a 57% NSR.
- Snow Angels (Mira Books, 10/01 reissue) reached #35 on the New York Times extended bestseller list and achieved a 54% NSR.
- 7B (
```

**Claim 11 (c000/0/002):** The blurb lists multiple prior titles.

Your label: TRUE

**Claim 12 (c000/0/005):** The mid-sequence list establishes a rhythm.

Your label: TRUE


---
## Context c051

```
by Ted Manna
American Reporter Correspondent
Colorado Springs, Colo.
September 7, 2008
PALIN: OUT OF THE PLANE AND INTO THE FIRE
COLORADO SPRINGS, Colo., Sept. 6, 2008-- This is how it starts, this elaborate electoral dance with the country's voters. Republican candidate for president Sen. John McCain and Gov. Sarah Palin stepped off their brightly-lit Straight Talk Air chartered jet last night, into a cool mist visible in the blazing headlights of the happy caravan that waited to carry them straight toward their date with destiny - Election Day.
It won't be cool and misty around Gov. Palin for long, however.
The campaign of Democratic presidential candidate Barack Obama has already sc`ored her for attracting some $300 in earmarks for every man, woman and child in Alaska - compared to the national average of $30 per person in other states.
She quickly struck back on Saturday, though, saying Sen. Obama had won more than abillion dollars in earmarks for hi Illinois constituency. "Just wait till John McCain puts a stop to that," she said. McCain pleaded in his acceptance speech last Thursday night to end the coveted earmarks that cost American taxpayers billions of dollars each year but individually benefit just a few in their home states.
The long-distance exchange as she related it was nonetheless enough to spark wild cheers and applause from an appreciative audience. In the words of one campaign worker, she "has ignited this campaign like a California wildfire."
The nominees brought their "Road to Victory Rally" to this Rebublican bastion in the shadow of the mighty Pikes Peak Friday afternoon, and the 10,000 tickets distributed didn't come close to meeting the demand.
The 85,000 voices cheering for the Democrats' presidential pick, Sen. Barack Obama, 60 miles north in Denver, had barely died away before the reverberations of McCain's stunning vice-presidential selection reached the Rocky Mountains.
In this sprawling city at the foot of the Rockies that is home to the U.S. Air Force Academy and widely known for its conservative voters
```

**Claim 13 (c051/0/008):** "Known for its Republican lean and its conservative voters" sets up further continuation.

Your label: RELATED_FALSE


---
## Context c013

```
Articles by John Piper
Born March 31: Rene Descartes, 1596 (“I think, therefore, I am”), Joseph Hayden, 1732 ("The Creation" Oratorio), and Barnabas William Piper, 1983 (Son of Encouragement).
Things just keep getting better and better.
Happy birthday, Barna!Continue Reading
“Lead us not into temptation, but deliver us from evil.” (Matthew 6:13)
James 1:13 says, “Let no one say when he is tempted, ‘I am being tempted by God,’ for God cannot be tempted with evil, and he himself tempts…Continue Reading
The Cluster Meetings are mainly for information and interrogation
The All Church Dinner is mainly for inspiration and adoration.
- Starting with the Deacon Council, Board chairmen and spouses on Friday, March 4, there will be 12…
Char and I have talked about this for months. A couple of times I think I succeeded in persuading her that staying was best. But this time she was more sure about the wisdom of returning to public school teaching…Continue Reading
Great things continue to happen at Bethlehem but, of course, that doesn’t mean everything is easy or that everything is as it should be. A week ago
```

**Claim 14 (c013/507/013):** Examples of such incidents include "a key leader was fired" or "a conversation about…".

Your label: UNVERIFIABLE


---
## Context c157

```
metadata: {"parentUuid": "a01b8497-b968-436d-a85e-6f5b56ff32b1", "isSidechain": false, "userType": "external", "cwd": "/Users/soph/Work/entire/devenv/cli", "sessionId": "2a55af89-4e4f-4460-b18f-42a07287ae76", "version": "2.1.37", "gitBranch": "soph/gemini-rewind", "slug": "tingly-shimmying-tiger", "type": "progress", "data": {"type": "hook_progress", "hookEvent": "PostToolUse", "hookName": "PostToolUse:Grep", "command": "callback"}, "parentToolUseID": "toolu_01WDTPbgnZdNoYMCWxhbNh3V", "toolUseID": "toolu_01WDTPbgnZdNoYMCWxhbNh3V", "timestamp": "2026-02-10T12:06:19.877Z", "uuid": "25b3a5b5-91f8-4627-a78e-226c97eaf431"}
tool_result: 60:		checkpoints, err := store.ListTemporaryCheckpoints(context.Background(), state.BaseCommit, state.WorktreeID, state.SessionID, limit)
67:			sessionPrompt, ok := sessionPrompts[cp.SessionID]
70:				sessionPrompts[cp.SessionID] = sessionPrompt
80:				SessionID:        cp.SessionID,
207:			if cpInfo.SessionCount > 1 && len(cpInfo.SessionIDs) > 1 {
208:				sessionPrompts = ReadAllSessionPromptsFromTree(metadataTree, checkpointPath, cpInfo.SessionCount, cpInfo.SessionIDs)
228:			SessionID:      cpInfo.SessionID,
231:			SessionIDs:     cpInfo.SessionIDs,
278:	sessionID,
```

**Claim 15 (c157/0/000):** The text is a grep/search-output log of Go source code lines containing `sessionID` in various contexts.

Your label: TRUE


---
## Context c228

```
 the popular Hobie Cat catamaran.

History 
Rancho Boca de la Playa, granted to Don Emigdio Vejar, was the initial land title issued in the area now known as Capistrano Beach. The land was sold to Juan Abila in 1860, and then purchased by Marcus A Forster in 1886. Forster sold a strip of the land to the San Bernardino and San Diego Railway. The railway, in collaboration with the California Central Railway, built a rail line between Los Angeles and San Diego, with a station at Capistrano. The station was initially named San Juan by the Sea, but in 1910 was changed to Serra, the name of the newly formed school district.

Development of Capistrano Beach started in 1925 with residential homes on the bluff. The Capistrano Beach Club was built along the shore of the new development. In 1929, the Petroleum Securities Company (owned by Edward L. Doheny) became the new owners of the Capistrano Beach development. In 1931, following the death of Doheny's son, he donated over  to the state for Doheny State Beach. Capistrano Beach became part of the city of Dana Point in 1989.

During the excavation of the land during development in 1929, the bones of a mastodon (or possibly a mammoth) were discovered. The bones were taken to the Los Angeles National History Hall for display.

The  wooden pier was popular for strolling, sightseeing, and fishing. The pier was severely damaged by waves in 1964, after which it was condemned and demolished in 1965. The Capistrano Beach Club became rundown and, in the late 1960s, was dismantled.

During storms in 2018, a boardwalk
```

**Claim 16 (c228/0/006):** "Due to heavy storms and erosion, in 2017 a boardwalk" strongly implies a damaged/washed-out/restructured boardwalk connecting to the beach or park area.

Your label: RELATED_FALSE


---
## Context c066

```
4 Common Startup Mistakes To Avoid
Posted on July 25, 2012 by nina
Published by Fast Company
With all the startups I’ve seen, and I’ve coached over 700 by now, I’ve become somewhat of an expert on common mistakes startups make. So when I find someone doing it right, I like to share.
Thomas Franchise Solutions is like no other startup I’ve worked with. Peter Thomas, the founder, is not a twenty-something. He is a mature, visionary leader, a man who has learned from his own experience as a serial entrepreneur how to start and run a company aligned with his personal values. He’s very blunt about telling you what those values are: health, happiness, freedom, and integrity. After retiring, he spent the last decade giving workshops and training others in values-based leadership. He donates the proceeds to charity.
That’s why, when he came out of retirement this year to start another company (he was bored), he was able to raise $13 million from friends and acquaintances to capitalize it. When he started making phone calls to raise money, he had already avoided the four most common startup mistakes: lack of a clear business model, insufficient market knowledge, not investing in human capital, and taking too much money.
Have a clear business model: Thomas picked a business at the intersection point of two industries he knew well, franchising and real estate. Real estate is a large part of the expansion of a franchise, because most of them involve brick and mortar. His experience bringing Century 21 to Canada and becoming involved with a massage franchise gave him the franchising experience, while the fact that he developed a luxury hotel in Arizona gave him depth in real estate. He had the business model: find franchisors of a certain size and experience who need to get to the next level, inject some capital into their businesses, and provide the strategic expertise along with the capital. Thomas Franchise Solutions, I’d guess, is a new kind of cross between a private equity firm, a VC and a consulting firm.. The business will have several revenue streams: return on the capital invested
```

**Claim 17 (c066/0/001):** It is now detailing a proposed green equity investment business model for CPs.

Your label: RELATED_FALSE


---
## Context c071

```
Terms and Conditions
7 August 2013
Thank you for visiting this website (the "Site"). By using this Site, you accept these Terms and agree to abide by them. If you do not accept these Terms, do not use this Site. We may change these Terms from time to time, so you should review them each time that you visit the Site. You should print a copy of these Terms for future reference.
1. About us
1.1 This Site is operated by Local World Ltd, a company registered in England under company number 08290481 with a registered office at PO Box 10177, 50 St George Street, Leicester LE1 8ED ("we", "us", "our"). You can contact us using the following email address: firstname.lastname@example.org
2. Using our Site
2.1 You may view (and, where applicable, listen to) the content available on the Site for personal non-commercial use. You may occasionally print individual webpages on the Site for your private non-commercial use, provided that such printing is not substantial or systematic and our trade marks and copyright and trade mark notices are not removed.
2.2 Unless otherwise stated in these Terms, you must not (whether directly or indirectly) copy, download, store, make available, distribute, sell or offer to sell all or any part of the content or Site, or download or otherwise copy (whether directly or indirectly) any content, files or data from the Site to make or populate a database or publication of any kind whatsoever.
2.3 You must not use all or any part of our Site or the contents on it for commercial purposes without our permission.
2.4 Users, whether or not registered, must not abuse our Report Abuse facility e.g. by making malicious reports.
3.1 You must choose an email address which gives you frequent access to emails sent to that address, as we need to be able to contact you. You must keep your password confidential.
```

**Claim 18 (c071/0/004):** Password security rules logically lead to liability, account misuse, or security responsibilities.

Your label: UNVERIFIABLE


---
## Context c203

```
 of her life. She began ballet classes at the age of six with the Jackson Ballet School, was a competitive swimmer winning many trophies through her school years, and was a cheerleader during her jr. high and high school days at Chastain Jr. High School and Manhattan High School. In 1976, she married Keith Thibodeaux, a former child actor and musician who appeared on I Love Lucy and The Lucy-Desi Comedy Hour television shows and later drummer for the groundbreaking Christian rock band David and the Giants.  They have one daughter, Tara Thibodeaux Drew (b. 1979), a dancer, teacher and choreographer, who is married to former NBA player and college basketball coach Bryce Drew, and one grandson, Bryson.

At the Jackson Ballet School (later Ballet Mississippi), Kathy studied under American Ballet Theatre’s Albia Kavan and Rex Cooper.  When the Jackson Ballet Company turned professional in 1978 under the direction of Thalia Mara, Kathy became one of the first dancers to be contracted, soon soaring to the highest levels of the company and becoming a Principal Dancer, a position she held until 1986.

Kathy stepped into the spotlight of the international dance world in 1982, winning a Silver Medal at the II USA International Ballet Competition which rotates between Jackson and Russia, Finland and Bulgaria. For the third contemporary round in that competition, against the advice of many, Kathy chose to express her faith in a dance to Sandi Patty’s "We Shall Behold Him".

In 1986 Keith and Kathy founded Ballet Magnificat!, recognized as "America's premier Christian ballet company". Kathy had a passion and unique vision for something totally unheard of – a touring Christian ballet troupe that would dance to the glory of God.  She envisioned Christian dancers coming together for the purpose of glorifying God in dance. In addition to bringing people into worship, Kathy
```

**Claim 19 (c203/143/004):** The text is building toward Kathy's visionary mission and contributions.

Your label: TRUE


---
## Context c221

```
 Ram Mukherjee's Bengali-language film Biyer Phool and in the social drama Raja Ki Aayegi Baaraat (both 1996). Mukerji had her first commercial success with the action film Ghulam and breakthrough with the romance Kuch Kuch Hota Hai (both 1998). Following a brief setback, the year 2002 marked a turning point for her when she was cast by Yash Raj Films as the star of the drama Saathiya.

Mukerji established herself by starring in several commercially successful romantic films, including Chalte Chalte (2003), Hum Tum (2004), Veer-Zaara (2004), and Kabhi Alvida Naa Kehna (2006), and the crime comedy Bunty Aur Babli (2005). She also gained praise for playing an abused wife in the political drama Yuva (2004) and a deaf and blind woman in the drama Black (2005). Mukerji's collaborations with Yash Raj Films from 2007 and 2010 produced several unsuccessful films and led critics to bemoan her choice of roles. This changed when she played a headstrong journalist in the thriller No One Killed Jessica (2011). Further success came with the thrillers Talaash (2012), Mardaani (2014) and Mardaani 2 (2019), the comedy-drama Hichki (2018), which emerged as her highest-grossing release, and the drama Mrs. Chatterjee vs Norway (2023).

Mukerji is involved with humanitarian causes and is vocal about issues faced by women and children. She has participated in concert tours and stage shows, and featured as a talent judge for the 
```

**Claim 20 (c221/0/006):** Dutt has frequently collaborated with director Rohit Shetty, producing several commercial successes.

Your label: RELATED_FALSE


---
## Context c101

```
tool_use: {"command": "mise run lint 2>&1", "description": "Full lint output", "timeout": 120000}
tool_result: Exit code 1
[lint] $ golangci-lint run ./...
cmd/entire/cli/strategy/rewind_test.go:296:19: string `claude-code` has 3 occurrences, make it a constant (goconst)
		if ag.Name() != "claude-code" {
		                ^
1 issues:
* goconst: 1
[lint] ERROR task failed
tool_use: {"file_path": "/Users/soph/Work/entire/devenv/cli/cmd/entire/cli/strategy/rewind_test.go", "offset": 1, "limit": 15}
metadata: {"parentUuid": "a8e22e49-630a-4ebb-b4a6-746ea7e2ee48", "isSidechain": false, "userType": "external", "cwd": "/Users/soph/Work/entire/devenv/cli", "sessionId": "2a55af89-4e4f-4460-b18f-42a07287ae76", "version": "2.1.37", "gitBranch": "soph/gemini-rewind", "slug": "tingly-shimmying-tiger", "type": "progress", "data": {"type": "hook_progress", "hookEvent": "PostToolUse", "hookName": "PostToolUse:Read", "command": "
```

**Claim 21 (c101/52/007):** `"command": "` opens a JSON string value in `lastToolInvocation.command`.

Your label: RELATED_FALSE

**Claim 22 (c101/52/008):** A shell command string is required to close the JSON string value in `lastToolInvocation.command`.

Your label: RELATED_FALSE


---
## Context c093

```
Minister for inform as great as informative affairs Abul Kalam Azad pronounced kid reporters have been personification a critical purpose in strengthening a children’s rights transformation by their writings.
He came up with a regard whilst inaugurating a two-day National Child Journalists Summit-2011 during a assembly residence of Bangladesh Institute of Administration as great as Management (BIAM) in a city Tuesday.
Journalism Institute “Shishu Prakash” mutually run by Mass-line Media Center (MMC) as great as UNICEF have orderly a summit. More than 600 kid reporters from opposite tools of a nation have been in attendance a summit.
“As a supervision has upheld a Right to Information Act as great as believes in giveaway upsurge of information, we have ensured sum leisure of press,” pronounced a minister.
Among others, Dhaka University Vice-chancellor highbrow Dr. AAMS Arefin Siddique as great as UNICEF nation executive Carol D. Roy attended a rite as special guests.
Terming kid broadcasting a singular e.g. in a history, VC Arefin said, “All a young kids contingency be courteous to posterior their studies as many of today’s kid reporters competence widespread out to assorted fields, such as healing as great as engineering, in a future.”
Mentioning a origination of broadcasting sanatorium spoken “Shishu Prakash” which constructed around 3,000 pup journalists, UNICEF arch Carol D. Roy said, “They have highlighted children’s problems as great as possibilities by their broadcasting practice.’’
Executive executive of MMC
```

**Claim 23 (c093/0/007):** MMC was previously mentioned as the programme's partner organization, "MMC in 2006".

Your label: RELATED_FALSE


---
## Context c272

```
", the only single released from Lies, peaked at number four on the Billboard Hot 100. This is the band's last full album to feature drummer Steven Adler following his departure in 1990, shortly after the single "Civil War" was recorded, and featured on Use Your Illusion II (1991), as well as their last album to be recorded as five-piece band members.

Background and recording

Live ?!*@ Like a Suicide

The first four tracks consist of the previously released EP Live ?!*@ Like a Suicide. These four tracks were also included as bonus tracks on the 2018 reissue of Appetite for Destruction.

G N' R Lies 
The last four songs were recorded with acoustic guitars. They were written and recorded in only a few studio sessions (with the exception of "You're Crazy", which appeared in an alternative version on Appetite for Destruction), which producer Mike Clink called "one of those magical rock and roll history moments".

In later interviews, Axl Rose stated that while he loved how the band sounded on the last four songs, he hated the sound of his voice. Rose recalled that his voice was husky and scratchy from the band's lengthy touring at the time, and if he could he would have re-recorded his vocal tracks in a separate session.

A significantly faster version of "You're Crazy" with electric guitars had previously been released on the band's debut album, Appetite for Destruction, and was now recorded as originally intended. 
"Used to Love Her" was written as a joke after Izzy Stradlin disliked a song he heard on the radio featuring "some guy whining about a broad who was treating him bad". Slash stated that "People think it's about one of our old girlfriends, but it's actually about Axl's dog."

Three of the four songs from the G N' R Lies EP are included on the 201
```

**Claim 24 (c272/0/003):** This is a sequential descriptive passage continuing chronologically.

Your label: RELATED_FALSE


---
## Context c227

```
 to science and named the creature Megalonyx. The cave from which these fossils were taken later came to be identified with Organ Cave.

20th century

1990
 Frederick A. Sundberg, and other colleagues erected the new ichnospecies Hylopus hamesi to hold fossil amphibian footprints from the latest Mississippian Bluefield Formation. This ichnospecies represented the oldest evidence for terrestrial vertebrates in the eastern United States. Based on the anatomy of the foot responsible for the traces, the researchers concluded that the tracks were left by anthracosaurs, possibly the species Protergyrinus scheelei, which was also known from West Virginia's Mississippian deposits. Variations in the structure of the trackways suggested that some of them were left while the animal was swimming, and thus the tracks suggest it was capable of walking on land and swimming underwater.

1993
 Two pieces of a Megalonyx shoulder blade were found in Haynes Cave of Monroe County, West Virginia, suggesting it may have been the true location where the Megalonyx bones examined by Thomas Jefferson were discovered, rather than Organ Cave.

1995
 Fred Grady further debunked the association between the Megalonyx fossils and Organ Cave since the original discovery site was owned at the time of the discovery by a man named Frederic Gromer, who had never owned Organ Cave. However, he did own Haynes Cave. Additional details gleaned from descriptions of Haynes Cave taken from the correspondence of subsequent owner, Tristram Patton, add more evidence that it was the true site of the discovery of Megalonyx.

21st century
2008
 Megalonyx jeffersonii was designated the West Virginia state fossil.

See also 

 Paleontology in West Virginia

Footnotes

References

 "Grady, Fred. "The Search for the Cave From Which Thomas Jefferson Described the Bones of the Megalonyx". Selected Abstracts From the 1995 National Speleological Society National Convention in Blacksburg, Virginia. Journal of Cave and Karst Studies, April 1997.
 Sundberg, Frederick A., J. Bret Bennington, Michael C. Wizevich, Richard K. Bambach. "Upper Carboniferous (Namurian) amphibian trackways from the Blue
```

**Claim 25 (c227/0/007):** This directly mirrors earlier text referencing the "Bluefield Formation of westcentral Virginia".

Your label: RELATED_FALSE


---
## Context c068

```
name = TEC_WP; Erp at the Speed of Light: Making Rapid Implementation Work for You by Oracle --> Email this to a friend View More Related Papers Receive White Paper Updates White Paper Description Users implementing enterprise resource planning (ERP) software for the first time are often intimidated by the time and cost, and want to accelerate the go-live date.
Related to Time and Cost: Decision Making, Enterprise Resource Planning (ERP), Installation (Support and Pre-installation), Needs Analysis, Return on Investment (ROI), Software Selection, Total Cost Analysis (TCO), Oracle
American Crane & Equipment Corporation (ACECO) designs and manufactures electric overhead traveling cranes. Managing and tracking custom projects for accurate job costing is key?but ACECO?s legacy system involved labor-intensive, manual manipulation of data. ACECO saw that real-time job cost data was vital to operational performance. It found a solution with integrated functionality for all process operations. Learn more.
Related to Time and Cost: Engineer-to-Order (ETO), Enterprise Resource Planning (ERP), Job Costing, Manufacturing Process Management (MPM), Operations Planning, Jobscope
To manage any resource, one must first see it clearly by tracking it carefully. Hence, time tracking should be a fundamental part of any business. Certainly, every business already tracks time at some level?even if only for payroll. The most successful businesses, however, understand that time tracking is a core business process, and they use that process to best advantage.
Related to Time and Cost: Payroll, Project Management, Project Portfolio Management (PPM), Time and Attendance Tracking, Time and Expense Reporting, Time, Billing, and Invoicing
```

**Claim 26 (c068/0/008):** The text includes a long Tags: list beginning "Tags: Employee Performance and Time Tracking, Remote Access and Virtual Desktop Solutions, Scheduling, Timekeeping, Web-Based Time Reporting and Scheduling, Time Management, Scheduling, and Time, Timeclock, and Time Tracking, and Billing, Time Tracking, Time Scheduling, and Timekeeping and Billing".

Your label: RELATED_FALSE


---
## Context c075

```
Blogger: Steve Rowland, Public Affairs Manager
Spring seemed a long way off last week as I took my lunchtime walk through the woods, the leaves on the trees were yet to unfurl, the ground was bare and covered in a mulch of last autumns dead leaves, and a light, cold wintry rain drizzled down.
And yet I realised that my mind had picked up on the subtle changes in the quality of light and drawing out of the days. I became aware of a slight tightness in my ears, an unconscious straining and heightened alertness to the bird song around me. And I thought that after more Springs as a birder than I care to remember, my brain was quietly and unobtrusively saying to my ears to be alert for couple of unremarkable notes of bird song one up followed repetitively by another down, up and down in short bursts, from a bird that takes its name from these two notes of song, the chiff chaff. (photo below).
Naming a bird after the sound it makes is known as onomatopoeia and two other species that occur in the UK the cuckoo and the kittiwake also take their names from their calls.
I will acknowledge here
```

**Claim 27 (c075/0/004):** This builds a detailed appreciation.

Your label: TRUE

**Claim 28 (c075/0/006):** "I will acknowledge here" is a transitional self-referential phrase mid-flow.

Your label: TRUE


---
## Context c256

```
 one of the seasonal residences of the regional king of Dumnonia. A castle was built on the site by Richard, 1st Earl of Cornwall in the 13th century, during the High Middle Ages. It later fell into disrepair and ruin.

Archaeological investigation into the site began in the 19th century as it became a tourist attraction, with visitors coming to see the ruins of Richard's castle. In the 1930s, excavations revealed significant traces of a much earlier high status settlement, which had trading links with the Mediterranean world during the Late Roman period. Two digs in 2016 and 2017 at Tintagel Castle uncovered the outlines of a palace from the 5th or early 6th century (the early medieval period), with evidence of writing and of articles brought in from Spain and from the eastern end of the Mediterranean Sea. The Cornwall Archaeological Unit has a five-year project at this site, with a final report expected in 2021. The items found in the digs have spurred interest before this final report, with two television programmes initially aired in 2018 or 2019, one in the UK by the BBC and another in the US by PBS.

The castle has a long association with legends related to King Arthur. This was first recorded in the 12th century when Geoffrey of Monmouth described Tintagel as the place of Arthur's conception in his mythological account of British history, Historia Regum Britanniae. Geoffrey told the story that Arthur's father, King Uther Pendragon, was disguised by Merlin's sorcery to look like Gorlois, Duke of Cornwall, the husband of Igraine, Arthur's mother.

Tintagel Castle has been a tourist destination since the mid-19th century. Owned by William, Prince of Wales as part of the landholdings of the Duchy of Cornwall, the site is managed by English Heritage.

History

Romano-British period
In the 1st century AD, southern Britain was invaded and occupied by the Roman Empire. The territory of modern Cornwall was assigned to the Roman administrative region of civitas Dumnoniorum, named after the local British tribal group whom the Romans called the Dumnonii. At the time, this south-westerly point of Britain was "remote, under-populated ... and therefore also unimportant
```

**Claim 29 (c256/0/003):** The text explains early settlement significance, Roman fort at Dorchester, and strategic geography of Southwest Britain.

Your label: RELATED_FALSE


---
## Context c176

```
tool_use: {"file_path": "/Users/soph/Work/entire/devenv/cli/cmd/entire/cli/agent/geminicli/types.go"}
metadata: {"parentUuid": "f4964258-451f-4390-aabf-304c113a0701", "isSidechain": false, "userType": "external", "cwd": "/Users/soph/Work/entire/devenv/cli", "sessionId": "2a55af89-4e4f-4460-b18f-42a07287ae76", "version": "2.1.37", "gitBranch": "soph/gemini-rewind", "slug": "tingly-shimmying-tiger", "type": "progress", "data": {"type": "hook_progress", "hookEvent": "PostToolUse", "hookName": "PostToolUse:Read", "command": "callback"}, "parentToolUseID": "toolu_01Wx1FvManAF7BRVHLtyeFJf", "toolUseID": "toolu_01Wx1FvManAF7BRVHLtyeFJf", "timestamp": "2026-02-10T12:07:50.567Z", "uuid": "b5dfbb4a-0fbb-4282-bae8-7c85c5650bd5"}
tool_result:      1→package geminicli
     2→
     3→import "encoding/json"
     4→
     5→// GeminiSettings represents the .gemini/settings.json structure
     6→type GeminiSettings struct {
```

**Claim 30 (c176/0/002):** A concrete example is requested: an explicit `claude.json` schema definition for "Claude's configuration file".

Your label: RELATED_FALSE


---
## Context c028

```
Nicholas A. Basbanes, a regular contributor to Fine Books & Collections has a nice article this month about the Brattle Book Shop in Boston. The title of the article claims "oldest bookstore in America," and Basbanes traces its origins to 1825.
In my collection of ephemera, I have a book dealer's calendar from 1901. His name is W.F. Tenney and his calendar advertisement states "old books bought and sold." His shop was located at 26 Brattle Street. Could Tenney have been neighbors with the Brattle Book Shop? Were they the only book dealers on Brattle St. or was there a lively book community in that area?
On Brattle Street, in Scollay Square, the Brattle Book Shop was born and christened by its location. There it thrived until the 1960s when it succumbed to area redevelopment projects and relocated. No telling whatever came of Tenney. His business may not have been around to see the 1960s. Perhaps it continued under another name or was purchased by another dealer. At least for awhile, around the turn of the last century, there were a couple of book shops on Brattle St. in Boston for collectors to find old books.
Six Score and More: Wallowing in It with Bill Reese - I've been recently wallowing in rare books with noted bookseller Bill Reese. Not literally, but via the Rare Book School podcast of his June 15, 2016 ta...
1 week ago
```

**Claim 31 (c028/0/008):** The text includes the content "View on iTunes…\n2 weeks ago".

Your label: RELATED_FALSE


---
## Context c039

```
How did it all begin? We hear that often and the truth be told, there was no great business plan or any plan at all, really, just a comment, a thought, an item on a bucket list. In October of 2011 at a home brewers’ gathering held at the farm of Jane and Craig Deitz, Craig planted the seed with a comment to his friend, Brad Paulson, about a desire to have a micro-brewery on Green Bluff. Brad’s response, “I’m in”.
And so it began. With collectively over 50 years of home brewing experience between them, Craig’s background in chemistry and Brad’s expertise in construction, a friendship became a partnership. Over a beer on a snowy winter’s day, Craig drew a schematic of the lay out of the brewery system. With the help of family and friends, construction of the big barn took place in the summer of 2012. As fate would have it, the building of the barn itself inspired daughter-in-law, Camille Dietz, to suggest the name – “Big Barn Brewing Company”. A soft opening took place for Oktoberfest 2012 and the response to a brewery on Green Bluff was overwhelmingly positive. The summer of 2013 brought home brew enthusiasts to the bluff in droves, arriving in cars, motorcycles, bicycles and limousines. Continuing to brew on two nano systems the two home brewers struggled to keep up with the demand, sometimes brewing five batches a week. With the installation of a seven barrel system in early 2014, Big Barn was able to move into full production that summer.
Our goal is to be self-sustaining, using farm produce from the Deitzes’ own farm as well as the surrounding farms, and has resulted in the production of such brews as our Blackberry
```

**Claim 32 (c039/0/001):** It is a narrative profile of a local establishment in Wisconsin.

Your label: RELATED_FALSE


---
## Context c177

```
tool_use: {"file_path": "/Users/soph/Work/entire/devenv/cli/cmd/entire/cli/strategy/manual_commit_rewind.go", "offset": 40, "limit": 100}
metadata: {"parentUuid": "88d261ca-6b62-415e-b3a1-bf48ee4de100", "isSidechain": false, "userType": "external", "cwd": "/Users/soph/Work/entire/devenv/cli", "sessionId": "2a55af89-4e4f-4460-b18f-42a07287ae76", "version": "2.1.37", "gitBranch": "soph/gemini-rewind", "slug": "tingly-shimmying-tiger", "type": "progress", "data": {"type": "hook_progress", "hookEvent": "PostToolUse", "hookName": "PostToolUse:Read", "command": "callback"}, "parentToolUseID": "toolu_01Br7ZupycUgQnzfNfezPbEi", "toolUseID": "toolu_01Br7ZupycUgQnzfNfezPbEi", "timestamp": "2026-02-10T12:08:05.377Z", "uuid": "e2a386d8-da79-4888-8b1b-970ec49d1012"}
tool_result:     40→	// Get current HEAD to find matching shadow branch
    41→	head, err := repo.Head()
    42→	if err != nil {
    43→		return nil
```

**Claim 33 (c177/0/004):** Domain-specific BIP/UTXO transaction logic is expected next.

Your label: UNRELATED_FALSE


---
## Context c249

```
 is now part of the Pomeranian Voivodeship in Poland.

History 
With the First Partition of Poland in 1772, the area of Marienburg became part of the Kingdom of Prussia and belonged there to the province of West Prussia, which was divided into six large districts, including the district of Marienburg. On 30 April 1815 the area became part of Regierungsbezirk Danzig with the province of West Prussia. As part of a comprehensive district reform, the old Marienburg district was significantly reduced in size on 1 April 1818. It now included the towns of Marienburg and Neuteich with their surrounding areas. The district capital was Marienburg. From 3 December 1829 to 1 April 1878, West Prussia and East Prussia were united to form the Province of Prussia, which belonged to the German Empire since 1871.

With the entry into force of the Treaty of Versailles on 10 January 1920 and the dissolution of the Province of West Prussia, the district of Marienburg was divided. The parts of the district lying to the west of the Nogat became part of the Free City of Danzig, while the area lying east of the Nogat remained in the German Reich and was provisionally subordinate to the Oberpräsident in Königsberg. To prepare for the referendum on the final membership of the district, the district area was soon subordinated to the Inter-Allied Commission for Government and Referendum in Marienwerder. After the clear result of the referendum in favor of Germany, the district remained in Germany. On 1 July 1922 the Marienburg district was formally incorporated into the province of East Prussia. Regierungsbezirk Marienwerder was renamed Regierungsbezirk West Prussia for reasons of tradition. The seat of the district president remained in Marienwerder.

On 1 September 1924 the rural communities of Tessensdorf and Willenberg from the Stuhm district were incorporated into the town of Marienburg in the Marienburg district. This was intended to compensate for the loss of territory it had suffered due to the establishment of the Free City of Danzig.

After the German invasion of Poland in 1939, the district of Marienburg became part of the newly formed Reichsgau Danzig-West Prussia, as part of Regierungsbezirk Marienwerder
```

**Claim 34 (c249/0/002):** The text is mid-sentence describing post-WWII Nazi administrative reorganization.

Your label: RELATED_FALSE


---
## Context c072

```
Posted Monday, November 26, 2012 --- 11:27 a.m.
Press Release from the City of Madison:
It's holiday recycling time. Madison residents have the chance to recycle cooking oil from their Thanksgiving feast and non working Holiday lights and extension cords at the Streets Division's drop off sites.
"We know that there are many people who have lots of oil left over after frying their Thanksgiving turkey," Madison recycling coordinator George Dreckmann said. "We are very excited to be able to offer them a chance to turn that old cooking oil into fuel for cars and trucks in our area."
Madison residents who wish to recycle their cooking oil must bring it to one of two Streets Division drop off sites. The sites are located at 1501 W. Badger Rd. on the west side and 4602 Sycamore Av. on the east side. Special cooking oil collection tanks are available at both of these locations.
"Every year thousands of gallons of old cooking oil is tossed in the landfill or flushed down the drain. Since we began our cooking oil program we have recovered over thousands of cooking oil" Dreckmann said. "Now we can recover this resource and use it to reduce our reliance on foreign oil and cut air pollution."
Cooking oil must be brought to the 1501 W. Badger Rd. or 4602 Sycamore Av. It should not be taken to the waste oil sites.
"We know that many residents are changing to new energy efficient LED holiday lights and have lots of older light strings they would like to dispose of," Madison recycling coordinator George Dreckmann said. "We are happy to provide them a recycling option for their old lights."
Madison will accept any light strings as well as old extension cords as part of the program. Residents who have older lights with large bulbs are asked to remove those bulbs. There is no need to remove bulbs from strings of mini lights.
"We will recycle all of the old lights through our electronics recycler Cascade Asset Management of Madison," Dreckmann said. "We will have a specially marked electronic collection container at the sites for
```

**Claim 35 (c072/0/004):** The final token "for" closes a prepositional phrase: "We also have a special recycling bin at each collection site for CFL lamps. We will accept these lamps in the bins. We will have a special recycling bin at the collection site for".

Your label: RELATED_FALSE


---
## Context c136

```
user: isProtectedPath() checks prefixes using "dir + '/'". relPath comes from filepath.Rel/Walk and will use OS-specific separators (e.g., "\" on Windows), so this can fail to detect protected paths on non-Unix platforms. Consider normalizing relPath/dir with filepath.ToSlash (or using string(filepath.Separator) consistently) before prefix checks.
tool_use: {"file_path": "/Users/soph/Work/entire/devenv/cli/cmd/entire/cli/strategy/common.go", "offset": 197, "limit": 12}
metadata: {"parentUuid": "b448fd7f-dba8-49f7-b528-de22de20389a", "isSidechain": false, "userType": "external", "cwd": "/Users/soph/Work/entire/devenv/cli", "sessionId": "2a55af89-4e4f-4460-b18f-42a07287ae76", "version": "2.1.37", "gitBranch": "soph/gemini-rewind", "slug": "tingly-shimmying-tiger", "type": "progress", "data": {"type": "hook_progress", "hookEvent": "PostToolUse", "hookName": "PostToolUse:Read", "command": "callback"}, "parentToolUseID": "toolu_014SxGbHxJhUjXcVXcvKQJpn", "toolUseID": "toolu_014SxGbHxJhUjXcVXcvKQJpn", "timestamp": "2026-02-10T11:57:56.642Z", "uuid": "19d354fb-f321-4cd8-982e-8f7418fb1b89"}
tool_result:    197→
  
```

**Claim 36 (c136/0/008):** There is a format inconsistency in the line number column with double-pipe spacing.

Your label: RELATED_FALSE


---
## Context c288

```
12.

Her senior club rowing in Australia was from the Melbourne University Boat Club. In MUBC colours she achieved three podium finishes in U21 sweep oared boats at the 2013 Australian Championships including a national title win in the women's coxless four. After graduation from Princeton she was back at the Australian championships in MUBC boats in 2018 and 2019. She achieved podium finishes in the coxless four in 2018  and in the coxless four and eight in 2019.

She attended Princeton University on a rowing scholarship and participated in their elite program. She rowed in the senior varsity VIII in all four of her Princeton years 2014 to 2017, won three Ivy-League titles in that time and in her senior year was the rowing team co-captain and a first team All-Ivy League honoree.

Howe was first selected to represent Victoria in the women's youth eight which contested the Bicentennial Cup in the Interstate Regatta at the 2013 Australian Rowing Championships. In 2019 Howe was selected in the Victorian the senior women's eight which contested and won the Queen's Cup at the Australian Interstate
```

**Claim 37 (c288/0/001):** The text covers medals, teams, and events for Australian rower Kate Martin.

Your label: RELATED_FALSE


---
## Context c274

```
 Road.

WTXK serves as the flagship station of the Troy Trojans and as a local affiliate of NASCAR racing via Motor Racing Network and Performance Racing Network. Programming includes syndicated programming from ESPN Radio.

In addition to the 1210 AM frequency, WTXK also broadcasts its programming on translator W298BC (107.5 FM) licensed to Montgomery. That station broadcasts from a transmitter at the studios of local television stations WAKA-TV, WNCF, and WBMM along Harrison Road in Montgomery.

History

The 1190 years
This station began regular broadcast operations on October 5, 1968, as a 1,000 watt daytime-only AM station at 1190 kHz known as WAYD under the ownership of Wade B. Sullivan. WAYD aired a country & western music format through the entire 1970s.

In October 1981, Wade B. Sullivan reached an agreement to sell WAYD to RJG Communications, owned by Raymond F. Akin, Gordon L. Bostic, and J.A. Baxter Jr.  The deal was approved by the FCC on December 3, 1981.  RJG Communications in turn agreed in February 1983 to sell this station to MSB Communications, Inc.  The deal was approved by the FCC on April 8, 1983.

Just over two years later, in August 1985, MSB Communications, Inc., contracted to sell this station to HS Communications, Inc.  The deal was approved by the FCC on September 18, 1985, and the transaction was consummated on February 10, 1986.

The 1200 years
WAYD received a construction permit on June 16, 1986, that authorized a move from 1190 kHz to 1200 kHz and a power increase to 10,000 watts during the day and to 2,500 watts during critical hours operation.  The station received its license to
```

**Claim 38 (c274/0/001):** The narrative follows a strict dated sequence of FCC applications, grants, and operational milestones.

Your label: RELATED_FALSE


---
## Context c253

```
such as meetups, CloudCamps, user group meetings, hackathons, free programming courses, etc.)

History 

Altoros was founded in 2001 as an outsourcing software development vendor. It then built platform-as-a-service and DevOps technology and provided consultancy around big data and cloud computing.

In 2007, Altoros founded Belarus Java User Group, which unites more than 500 Java developers in Belarus. Since 2008, Altoros has been arranging a variety of conferences and other events for IT specialists in Belarus, featuring Microsoft, Adobe, SUN Microsystems, and Engine Yard representatives as speakers.

In February 2007, Altoros launched Apatar, a Java-based data integration (ETL) project. The open source version of the product was released under the GPL 2.0 license.

In July 2008, Altoros became a resident of Belarus High Technologies Park, a business environment for IT companies in Eastern Europe that forces cooperation in IT on the inter-governmental level.

In 2010, Altoros co-founded Belarus Ruby on Rails User Group. To support this initiative, in August 2011, the company launched free educational Ruby on Rails training course for developers in Eastern Europe. Altoros also sponsors numerous Ruby conferences around the world (RubyConf in Argentina, Barcelona Ruby Conference in Spain, RubyConfBY in Belarus, etc.).

On October 11, 2011, Altoros officially organized
```

**Claim 39 (c253/0/006):** This continues the pattern of naming newly-established community/organizational entities.

Your label: UNVERIFIABLE


---
## Context c147

```
metadata: {"parentUuid": "1c55c619-e608-4565-9154-2b6ae97cd4fa", "isSidechain": false, "userType": "external", "cwd": "/Users/soph/Work/entire/devenv/cli", "sessionId": "2a55af89-4e4f-4460-b18f-42a07287ae76", "version": "2.1.37", "gitBranch": "soph/gemini-rewind", "slug": "tingly-shimmying-tiger", "type": "progress", "data": {"type": "bash_progress", "output": "", "fullOutput": "", "elapsedTimeSeconds": 9, "totalLines": 0, "timeoutMs": 120000}, "toolUseID": "bash-progress-7", "parentToolUseID": "toolu_01KAk5fbgcx6grDpxLncVh9m", "uuid": "b3f9a43c-db6e-4b1d-9a15-cb387a6c0ae5", "timestamp": "2026
```

**Claim 40 (c147/0/000):** The text is a debugging/error trace context.

Your label: RELATED_FALSE


---
## Context c044

```
Players Finger Markers: For the beginning student. Thin fingerboard tape minimizes string
buzzing while reinforcing finger positioning. Four dots, each with
three colorful dots.
Teachers Choice Fingerboard Tape:
Perfect for teachers and students. Fingerboard tape is durable, easy to apply, and is super thin to minimize string buzzing. Does not leave residue when removed. Available in single packages that contains six tapes, or on a continuous roll.
Mark Set Go:
Easy to use. Helps beginning students learn finger and thumb placement. Teachers Pack, enough for 12 instruments, includes both gold and silver cards with 2 thumb fuzzy.
The original Tourte rubber slips easily over the bridge when in use but may stay on the instrument when not in use for quick access. This mute is available in a two hole model for violin, viola, cello or string bass.
Don't Fret is the perfect finger marking tape for the first seven positions, or for first position only.
Made of thin, one-piece, self-adhering vinyl that lays flat on the fingerboard with no disruptive bumps that cause buzzing. Easy removal, and leaves NO residue. Available for all sizes of Violin, Viola or Cello.
First Frets: Four colorful and mathematically accurate stripes indicate the correct
placement of each of the four fingers in first position.
Don't Fret: Seven colorful and mathematically accurate stripes indicate the correct placement of each of the seven positions.
```

**Claim 41 (c044/0/001):** The catalog cycles through named products with descriptions, benefits, and specs for a swim school audience.

Your label: RELATED_FALSE


---
## Context c111

```
tool_result: ok  	github.com/entireio/cli/cmd/entire/cli/strategy	6.010s
ok  	github.com/entireio/cli/cmd/entire/cli/stringutil	(cached)
ok  	github.com/entireio/cli/cmd/entire/cli/summarize	(cached)
ok  	github.com/entireio/cli/cmd/entire/cli/telemetry	(cached)
ok  	github.com/entireio/cli/cmd/entire/cli/textutil	(cached)
ok  	github.com/entireio/cli/cmd/entire/cli/trailers	(cached)
ok  	github.com/entireio/cli/cmd/entire/cli/transcript	(cached)
ok  	github.com/entireio/cli/cmd/entire/cli/validation	(cached)
ok  	github.com/entireio/cli/cmd/entire/cli/versioncheck	(cached)
ok  	github.com/entireio/cli/redact	(cached)
assistant: All clean. Here's what the review pass fixed:

**Critical fix**: `resolveAgentForRewind` now uses `!isSpecificAgentType(agentType)` instead of `agentType == ""`, so old checkpoints with `"Agent"` (the `AgentTypeUnknown` fallback) correctly fall back to Claude instead of erroring.

**Stale comments fixed**:
- `common.go:1196` — no longer lists `.claude/`
```

**Claim 42 (c111/442/005):** Each bullet point addresses a distinct bug or feature.

Your label: TRUE


---
## Context c247

```
 to their highest post-war finish in the league, whilst he helped Bradford win promotion into the Premier League.

Playing career
Born in Mexborough, Mills started his career with Stocksbridge Park Steels before being brought to the Football League with Wolverhampton Wanderers, and Derby County.

In July 1995, he joined John Rudge's Port Vale as Derby paid £475,000 plus Mills in exchange for Robin van der Laan. He made his debut for the "Valiants" as a substitute on 13 August 1995, in a goalless draw with Derby at The Baseball Ground. At the end of the season Derby were promoted, but Vale finished in twelfth spot. On 13 October 1996, he came off the bench at the Victoria Ground to score a last minute equaliser in a Potteries derby game with Stoke City. He finished the  1996–97 season with fifteen goals and was handed the club's player of the year award as the club posted their highest post-war finish – eighth place in the First Division. During the 1997–98 season Mills was the club's top scorer with 16 goals, as Vale narrowly avoiding relegation.

Mills became Bradford City's first £1 million player when Paul Jewell purchased him in preparation for the 1998–99 season. Mills made a large contribution to Bradford's promotion to the Premier League, becoming the club's top scorer with 24 goals. He also scored on his return to Vale Park, perhaps with a point to prove after a Port Vale matchday programme article described him as "poor" and his touch as "frequently awful". The 1999–2000 season was a poor one for Mills, scoring just six goals as he was troubled with injury and had a falling out with manager Paul Jewell. He spent March 2000 on loan with First Division Manchester City. His poor form left him labelled as a "forgotten man" when he scored twice in the 2000 UEFA Intertoto Cup against Lithuanian side FK Atlantas. New manager Chris Hutchings put Mills on a list of seven "underachievers", with a warning that a continuation of poor form would see those players
```

**Claim 43 (c247/0/007):** This completes the threat of transfer/departure.

Your label: UNVERIFIABLE


---
## Context c105

```
tool_result:    286→
   287→	t.Run("empty type falls back to default agent", func(t *testing.T) {
   288→		t.Parallel()
   289→		ag, err := resolveAgentForRewind("")
   290→		if err != nil {
   291→			t.Fatalf("unexpected error: %v", err)
   292→		}
   293→		if ag == nil {
   294→			t.Fatal("expected non-nil agent")
   295→		}
   296→		// Default is Claude
   297→		if ag.Name() != agent.AgentNameClaudeCode {
   298→			t.Errorf("Name() = %q, want %q", ag.Name(), "claude-code")
   299→		}
   300→	})
   301→
   302→	t.Run("AgentTypeUnknown falls back to default agent", func(t *testing.T) {
   303→		t.Parallel()
   304→		ag, err := resolveAgentForRewind("Agent")
   305→		if err != nil {
   306→			t.Fatalf("unexpected error: %v", err)
   307→		}
   308→		if ag.Name() != agent.AgentNameClaudeCode {
   309→			t.Errorf("Name() = %q, want %q",
```

**Claim 44 (c105/208/000):** Code review diff format has been established.

Your label: RELATED_FALSE


---
## Context c223

```
 to gather data about minority groups in America.

Career
Ramakrishnan has a BA in international relations from Brown University, and a PhD in politics from Princeton University.

Ramakrishnan has written or edited seven books, including Citizenship Reimagined: A New Framework for State Rights in the United States (2020). He was the solo author of Democracy in Immigrant America: Changing Demographics and Political Participation (2005), which Pei-te Lien called "an unprecedented effort systematically to study political participation by immigrants and their offspring, across generations and major racial and national-origin groups". He has also published articles on topics like the integration of immigrants into American political society and public opinion regarding immigration in venues like Perspectives on Politics and the International Migration Review.

Ramakrishnan has founded and directed multiple projects related to data acquisition on minority groups in the US, including the National Asian American Survey, the AAPI Data project to collect information about Asian Americans and Pacific Islanders in the US, and the Inland Empire 2020 Census Complete Count Committee, an effort in San Bernardino County and Riverside County to raise awareness and conduct outreach to hard-to-count populations by the US Census. Ramakrishnan was also the founding editor of the Journal of Race, Ethnicity, and Politics.

Ramakrishnan's work has regularly been quoted, or had his work cited, in news outlets like NBC, Vox, the Los Angeles Times, The New York Times, and The Washington Post. He has also published articles in The Washington Post and CNN. In 2018, Ramakrishnan was named a member of the Frederick Douglass 200, a project by American University and the Frederick Douglass Family Initiatives to select "200 living individuals who best embody the work and spirit of Douglass".

Selected works
"Imm
```

**Claim 45 (c223/0/009):** This is an incomplete journal article title entry requiring completion, almost certainly continuing "Immigration," "Identity," or "Immigrant Voting."

Your label: UNVERIFIABLE


---
## Context c100

```
metadata: {"parentUuid": "69103bca-72a2-4d79-ae9d-cae797dbab26", "isSidechain": false, "userType": "external", "cwd": "/Users/soph/Work/entire/devenv/cli", "sessionId": "2a55af89-4e4f-4460-b18f-42a07287ae76", "version": "2.1.37", "gitBranch": "soph/gemini-rewind", "slug": "tingly-shimmying-tiger", "type": "progress", "data": {"type": "bash_progress", "output": "", "fullOutput": "", "elapsedTimeSeconds": 7, "totalLines": 0, "timeoutMs": 120000}, "toolUseID": "bash-progress-5", "parentToolUseID": "toolu_01BegG1g8obgeXHzLrVgYFQD", "uuid": "37eb7dcb-2c12-4045-84e3-cd73e5130c5d", "timestamp": "2026-02-10T11:07:05.109Z"}
tool_result: ok  	github.com/entireio/cli/cmd/entire/cli/strategy	6.516s
ok  	github.com/entireio/cli/cmd/entire/cli/stringutil	(cached)
ok  	github.com/entireio/cli/cmd/entire/cli/summarize	(cached)
ok  	github.com/entireio/cli/cmd/entire/cli/telemetry	(cached)
ok  	github.com/entireio/cli/cmd/entire/cli/textutil	(cached)
ok  	github.com/entireio/cli/cmd/entire/cli/trailers	(cached)
ok  	github.com/entireio/cli/cmd/entire/cli/transcript	(cached)
ok  	github.com/entireio/cli/cmd/entire/cli/validation	(cached)
ok  	github.com/entireio/cli/cmd/entire/cli/versioncheck	
```

**Claim 46 (c100/13/007):** The next `internal/` subpackage is likely the final package in the series.

Your label: RELATED_FALSE


---
## Context c001

```
Mixed Use Apartments and Retail Space in Downtown Indianapolis Coming Soon
Monday, April 21, 2014Print this Article | News Articles
Flaherty & Collins, one of the Midwest's largest developers of multifamily projects is completing another downtown 325 unit apartment complex with a supermarket and a parking garage. Located one block from the Downtown Canal, the $85 million project has been called a win for the city by Mayor Greg Ballard. The jobsite was once a parking lot north of the OneAmerica Tower. OneAmerica sold the ground to Flaherty & Collins. To make up for the hundreds of parking spots OneAmerica will lose to the project, the city will build the insurer a 930-space parking garage paid with $11 million in property tax money from Downtown's tax increment financing district. The apartments will be decidedly upscale, with monthly rents ranging from $1,075 for studios to $2,200 for two-bedroom units. Amenities will include a heated saltwater pool, fitness center and three courtyards.
The perforated panels on the parking garage were curved on site. The alternating pattern of four shades of blue were chosen to create a wave appearance. Supporting the panels is a subframing assembly unit. Interior work was also performed inside the ground level Marsh Supermarket. An aluminum composite metal panel was fabricated into signage in the deli department. The exterior walls of the apartment units incorporated profile metal wall panels into the
```

**Claim 47 (c001/39/011):** Fiber cement panels are utilized into the apartments' balcony rail details.

Your label: UNVERIFIABLE


---
## Context c052

```
Our favourite picks from Net-a-porter
Everybody’s favourite high-end shopping website Net-a-porter.com is adding a new range of everything designer from Monday, June 7, and the guys at NAP were kind enough to offer us a sneak peek into what’s going to be in-store for e-shoppers.
We loved the entire selection of new additions, but if we were to pick just eight, these would be our recommendations. Prepare your credit card for what’s clearly going to be strenuous workout.
1.) Alexander McQueen Leopard-print goat jacket
Cream, beige and black leopard-print goat jacket. Alexander McQueen jacket has an oversized collar that drapes at the front, a shorter back, long fitted sleeves, side-slit pockets, hook fastenings at the front and is fully lined in taupe silk-satin.
2.) Alexander McQueen Leather Biker Jacket
Black leather biker jacket with padded shoulders. Alexander McQueen jacket has a notched collar with four silver studs, is double-breasted with exposed silver zip-fastening, two silver zip slit pockets to the front, two press-stud fastening flap pockets to the front, one smaller press-stud fastening flap pocket to the front, belt loops to the front and back with press-stud fastening, a detatchable black leather belt, zips on the cuffs and leather elbow-patches.
3.) Emilio Pucci fringed dress
Dark-gray suede asymmetric dress with tiered fringing. Emilio Pucci dress has gunmetal hardware, two buckle details at shoulder, eyelet detail at neckline, exposed zip fastening at side, an asymmetric hem and is fully lined.
4.) Versace Leather & Cotton Blend Jacket
Purple crinkled leather and cotton-blend jersey-stretch jacket. Versace jacket has a notch collar, asymmetrical exposed gold zip fastening through front with designer-stamped tag, cotton-blend jersey-stretch panelling on the body and arms and patent purple strips either side of the zip.
5.) Alexander McQueen Crepe bustier dress
Cream floor-length creponne dress with bustier and draped skirt. Alexander McQueen dress inner boning and underwired cups, zip through bustier at the back and a hook to fasten.
6.) Alexander McQueen Peony-print crepe gown

```

**Claim 48 (c052/0/005):** The next token is likely "Multi-colored floral-print silk crepe gown" or similar complex color-name descriptor.

Your label: UNVERIFIABLE


---
## Context c280

```
 institutions utilizing Falkor commit to openly share and communicate the outcomes of their research, including raw observations and data. Research proposals are reviewed through a peer-reviewed process and assessed based on their potential for technological innovation, oceanographic research, and overall impact. Since its inception in 2009, SOI has supported over 60 expeditions all around the globe. 

Its footages are available under a CC-NC license.

Research vessels

The Schmidt Ocean Institute has operated two research vessels, R/V Lone Ranger and R/V Falkor. The Lone Ranger, a 255-foot former ocean tug, was donated to the Institute by Peter B. Lewis in 2009 and was operated by the Institute to support research in Bermuda and the Bahamas. 

In 2012 the Schmidt Ocean Institute completed the retrofit of a former German Fisheries protection vessel into a state-of-the-art oceanographic research vessel. The newly retrofitted vessel was renamed R/V Falkor after the luckdragon from The Neverending Story. R/V Falkor became fully operational for scientific use in 2013 following a year of sea trials. Since then, Falkor has hosted numerous international science teams and institutes, successfully supporting oceanographic research. In 2015, R/V Falkor became the first oceanographic research vessel with a high-performance computing system expanding data storage
```

**Claim 49 (c280/0/000):** The text is in an institutional/promotional register for a research vessel.

Your label: TRUE


---
## Context c070

```
A few more notes
*The Orioles will conduct an open tryout to find ballgirls and ballboys for the 2013 season at Oriole Park at Camden Yards on Saturday, March 9.
Outgoing and athletic men and women ages 18 and older who are interested in serving as ballboys and ballgirls for the Orioles during the upcoming 2013 season are invited to try out for a position at Oriole Park beginning at noon on March 9.
Those interested should dress casually, bring their own gloves, and use the Home Plate Plaza entrance to Oriole Park on the southwest corner of the ballpark. Resumes are also recommended. Complimentary parking will be available in Lot A.
In addition to being able to handle a glove and field ground balls, interested candidates should be personable, customer-service oriented and available to work the entire 2013 season.
*The Orioles have two players, Brenden Webb and Michael Ohlman, in the Australian Baseball League. Their them, the Perth Heat, are playing in the Championship Feb 8 – 10. Ohlman is a first baseman and through 43 games is hitting .317/.372/.527 with six homers and 27 RBIs, while Webb –who has primarily played right field– is hitting .190/.365/.466 with five homers and 10 RBIs in 18 games.
*In case you missed it, my colleague at Indians.com –Jordan Bastian– did a nice job chronicling the interesting winter of Russ Canzler, who was claimed by the Orioles (his fourth team this winter) earlier this week. You can read that story here.
```

**Claim 50 (c070/0/005):** The final item references Chris Carter's earlier signing and directs readers to a prior post for details.

Your label: RELATED_FALSE



................................................................................

ANSWER KEY - do not scroll here until all 50 are written down

................................................................................

1. c173/0/001: RELATED_FALSE  - There are no diff annotations or 'unchanged' markers in this tool_result output.
2. c180/0/006: UNVERIFIABLE  - This speculates about unseen struct fields.
3. c299/0/003: RELATED_FALSE  - The text discusses population genetics (the Kojima paper), not a transition to evolutionary game theory.
4. c086/0/001: TRUE  - The review covers production values, cast performances, and narrative/story background formally.
5. c133/0/001: TRUE  - The test/log output does follow a consistent formatting pattern.
6. c134/0/001: RELATED_FALSE  - The metadata repeats fields like cwd/sessionId/gitBranch, but there are no 'code task instructions' present.
7. c233/0/011: UNVERIFIABLE  - A generic, largely true-by-construction observation about any 1900s year constraint; not meaningfully checkable as a specific prediction.
8. c022/0/006: UNVERIFIABLE  - Speculation about what specific continuation follows the cutoff.
9. c276/0/009: UNVERIFIABLE  - This predicts the genre/type of the unseen next bibliographic entry.
10. c184/0/011: RELATED_FALSE  - The final token 'logging' is correct, but the text is not a diff, so 'added line' framing is false.
11. c000/0/002: TRUE  - The blurb lists Kiss Them Goodbye, The Orphan, and Snow Angels as prior titles.
12. c000/0/005: TRUE  - The three listed entries do form a repeating structural rhythm.
13. c051/0/008: RELATED_FALSE  - This quoted phrase about 'Republican lean' is invented and does not appear in the text.
14. c013/507/013: UNVERIFIABLE  - Speculative examples of continuation beyond the text's end.
15. c157/0/000: TRUE  - Text is a grep-style listing of Go source lines containing 'sessionID'.
16. c228/0/006: RELATED_FALSE  - Claim quotes the truncated sentence as "Due to heavy storms and erosion, in 2017 a boardwalk", but the context actually reads "During storms in 2018, a boardwalk" — wrong year and wrong wording for existing text.
17. c066/0/001: RELATED_FALSE  - The venture is a private-equity/VC/consulting hybrid investing in franchisors, not a "green equity" business for "CPs."
18. c071/0/004: UNVERIFIABLE  - Speculative reasoning about what topic logically follows password rules.
19. c203/143/004: TRUE  - The passage is building toward describing her vision/contributions.
20. c221/0/006: RELATED_FALSE  - No mention of director Rohit Shetty appears in the text, and the subject is Mukerji, not Dutt.
21. c101/52/007: RELATED_FALSE  - There is no field named 'lastToolInvocation.command' in the text; the actual key is under metadata.data.command.
22. c101/52/008: UNVERIFIABLE  - A generic prediction that a string is needed to close the value; not checkable.
23. c093/0/007: RELATED_FALSE  - No year like 2006 is given for MMC anywhere in the text.
24. c272/0/003: TRUE  - The passage is a sequential descriptive account of the album's recording history.
25. c227/0/007: RELATED_FALSE  - Earlier text says 'latest Mississippian Bluefield Formation', with no 'westcentral Virginia' phrase.
26. c068/0/008: RELATED_FALSE  - No such 'Tags:' list with this wording appears; the actual label is 'Related to Time and Cost:' with different keywords.
27. c075/0/004: TRUE  - The passage builds a detailed, sensory appreciation of the birder's noticing subtle seasonal changes.
28. c075/0/006: TRUE  - The text does end exactly on the phrase 'I will acknowledge here'.
29. c256/0/003: RELATED_FALSE  - No 'Dorchester' or Roman fort is mentioned; the text discusses civitas Dumnoniorum in Cornwall.
30. c176/0/002: RELATED_FALSE  - The text concerns Gemini's settings file, not a 'claude.json' schema for 'Claude's configuration file'.
31. c028/0/008: RELATED_FALSE  - The phrase 'View on iTunes...2 weeks ago' does not appear in the text.
32. c039/0/001: RELATED_FALSE  - Green Bluff, the brewery's location, is in Washington State, not Wisconsin.
33. c177/0/004: RELATED_FALSE  - False premise: the code is about git shadow branches, not BIP/UTXO transaction logic.
34. c249/0/002: RELATED_FALSE  - The final passage describes the 1939 Nazi-era reorganization during WWII, not a 'post-WWII' reorganization.
35. c072/0/004: RELATED_FALSE  - The final token 'for' is accurate, but the illustrative continuation about a 'CFL lamps' bin is invented; the text is about lights/cords recycling.
36. c136/0/008: RELATED_FALSE  - No such double-pipe formatting inconsistency is shown in the text.
37. c288/0/001: RELATED_FALSE  - The rower is named Howe in the text, not Kate Martin.
38. c274/0/001: TRUE  - Text follows a dated sequence of FCC sale approvals and construction permits.
39. c253/0/006: UNVERIFIABLE  - Predicts the nature of continuation content beyond the text's actual end.
40. c147/0/000: RELATED_FALSE  - This is a bash_progress tool metadata entry, not clearly an error/debugging trace.
41. c044/0/001: RELATED_FALSE  - The catalog is for music teachers/students (violin, viola, cello), not a 'swim school audience'.
42. c111/442/005: TRUE  - Each bullet (critical fix, stale comment) addresses a distinct, separate issue.
43. c247/0/007: UNVERIFIABLE  - Generic prediction about a transfer/departure threat; not checkable.
44. c105/208/000: RELATED_FALSE  - The visible text is raw Go test source with line numbers from a Read tool result, not code-review comments.
45. c223/0/009: UNVERIFIABLE  - Speculative guess at the completed title; not checkable.
46. c100/13/007: RELATED_FALSE  - This builds on the false 'internal/' subpackage premise from the previous claim.
47. c001/39/011: UNVERIFIABLE  - Asserts specific continuation content beyond where the given text stops.
48. c052/0/005: RELATED_FALSE  - This prediction is built on the false final-token quote from the prior claim.
49. c280/0/000: TRUE  - The passage uses an institutional/promotional register describing a research organization's vessels.
50. c070/0/005: RELATED_FALSE  - Final item is about Russ Canzler, not Chris Carter, and links to a colleague's Indians.com story, not 'a prior post'.
