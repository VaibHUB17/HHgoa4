<!-- Placeholders: [BLOG_LINK] and [DEMO_LINK] need real URLs once the blog is published
     and the demo video is uploaded.

     [VERIFY] "shared-device ring across two different customers" in the LinkedIn draft below
     was corrected to reflect the live run: HHG-014's ring spans 18 distinct customers' cards
     on one device, confirmed by TigerGraph's tg_wcc algorithm, not just two. Re-check this
     number against cases/HHG-014.json before publishing, since another agent is fixing a
     policy bug on this branch concurrently and the case set may be regenerated. -->

# Social drafts

## X / Twitter (under 280 chars)

Half the cases in this fraud dataset are legitimate. We built an agent that knows when NOT to
act: TigerGraph two-hop queries surface shared-device rings a per-transaction model can't see, and
it asks before it blocks. @TigerGraphDB [BLOG_LINK] [DEMO_LINK]

*(256 chars as written, before URL substitution. X shortens most links to ~23 chars each via
t.co, so real URLs should still fit comfortably under 280 — recount after swapping them in.)*

## LinkedIn (~150 words)

Most fraud-detection demos open with a dramatic block. We opened with the opposite: a case our
agent correctly left alone.

Working with the TigerGraph x Hacker House Goa dataset, the real problem wasn't classification —
there's no fraud label in the data, half of the twenty exam cases are legitimate, and the bank's
own risk score is wrong in both directions. So we built an agent that investigates under
uncertainty instead of scoring a single number: it queries the graph for evidence, asks for
verification when one signal isn't enough, and changes its recommendation when the answer comes
back — recording both the before and the after.

The graph is what makes it possible. One case starts from an analyst's note about a shared device —
a two-hop query turns up 18 customers' cards on the same device fingerprint, confirmed by graph
community detection, invisible to any model scoring one transaction at a time.

Write-up and demo: [BLOG_LINK] [DEMO_LINK]

Built on TigerGraph. Thanks @TigerGraphDB for the dataset and the task.
