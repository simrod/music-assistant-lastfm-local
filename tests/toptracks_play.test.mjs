import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const {
  createChartBook,
  createTopTracksSession,
  mediaUri,
  rewritePlayArgs,
  TOP_TRACKS,
  PLAY_MEDIA,
} = require("../lastfm_local/toptracks_play.js");

const chart = [
  { name: "Karma Police", uri: "library://track/1" },
  { name: "Creep", uri: "library://track/2" },
  { name: "Paranoid Android", uri: "library://track/3" },
];

const book = createChartBook();
book.add(chart);

assert.deepEqual(
  book.match(["Karma Police", "Creep"]).uris,
  ["library://track/1", "library://track/2", "library://track/3"],
);
assert.equal(book.match(["Creep", "Karma Police"]), null);
assert.equal(book.match(["Karma Police", "Creep", "Missing"]), null);
assert.equal(book.match([]), null);

book.add([{ name: "Other", uri: "library://track/9" }]);
assert.equal(book.match(["Other"]).uris[0], "library://track/9");
assert.deepEqual(book.match(["Karma Police"]).uris[0], "library://track/1");

book.add(chart);
assert.equal(book.match(["Karma Police"]).uris.length, 3);

const sessionBook = createChartBook();
const session = createTopTracksSession(sessionBook);
session.outgoing({ command: TOP_TRACKS, message_id: 1 });
session.outgoing({ command: TOP_TRACKS, message_id: 2 });
session.incoming({
  message_id: 1,
  result: [{ name: "Stale", uri: "library://track/stale" }],
});
assert.equal(sessionBook.match(["Stale"]), null);
session.incoming({
  message_id: 2,
  partial: true,
  result: [chart[0], chart[1]],
});
assert.equal(sessionBook.match(["Karma Police"]), null);
session.incoming({ message_id: 2, result: [chart[2]] });
assert.deepEqual(sessionBook.match(["Karma Police", "Creep", "Paranoid Android"]).uris, [
  "library://track/1",
  "library://track/2",
  "library://track/3",
]);
session.incoming({ message_id: 2, error_code: 1, result: [] });
assert.equal(sessionBook.match(["Karma Police"]).uris.length, 3);

session.outgoing({ command: "music/artists/artist_tracks", message_id: 3 });
session.incoming({
  message_id: 3,
  result: [{ name: "Newest", uri: "library://track/new" }],
});
assert.equal(sessionBook.match(["Newest"]), null);

assert.equal(mediaUri("library://track/1"), "library://track/1");
assert.equal(mediaUri({ uri: "library://track/2" }), "library://track/2");
assert.equal(mediaUri([{ uri: "library://track/3" }]), "library://track/3");
assert.equal(mediaUri([{ uri: "a" }, { uri: "b" }]), null);

const uris = ["library://track/2", "library://track/3"];
const rewritten = rewritePlayArgs(
  { queue_id: "player.room", media: { uri: "library://track/2", name: "Creep" }, option: null },
  uris,
);
assert.deepEqual(rewritten.media, uris);
assert.equal(rewritten.shuffle, false);
assert.equal(rewritten.queue_id, "player.room");
assert.equal(rewritten.option, null);

assert.equal(
  rewritePlayArgs({ media: { uri: "library://track/1" } }, uris),
  null,
);
assert.equal(rewritePlayArgs({ media: "library://track/3" }, ["library://track/3"]), null);
assert.equal(rewritePlayArgs({ media: { uri: "library://track/2" } }, null), null);

console.log("toptracks play script ok");
