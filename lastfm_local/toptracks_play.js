/**
 * Play an artist Top Tracks row the way an album plays.
 *
 * Music Assistant sends one track from that row. This script remembers each
 * top-tracks response and, when a play button in the row is used, sends that
 * track through the end of the chart instead. It has to load before the app
 * module so it wraps WebSocket before the app captures it.
 *
 * The row shows the first tracks of the response. Playback uses the whole
 * response, so tracks past the ones on screen are included. A row that is not
 * one of those responses (the newest-tracks fallback) is left alone.
 *
 * Music Assistant 2.17 draws this as a plain section. The heading is the
 * toolbar title "Top tracks" (the subtitle "On <provider>" is separate). The
 * account can save that section collapsed, which leaves the heading on screen
 * and does not draw the rows. Play all stays on the heading in that case.
 * Clicking it opens the section and replaces the current queue with the
 * chart, the way an album play does.
 *
 * Each track is a v-list-item. Vuetify wraps the title slot in
 * .v-list-item-title, and the name is the first text of the inner
 * .v-list-item-title. A version or year is a later span and is not part of
 * the chart name. Desktop play is the art (.listitem-media-thumb.is-playable).
 * A phone uses button.listitem-mobile-play. The dots menu is not play.
 */
(function (factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined" && window.document) {
    api.install();
  }
})(function () {
  var TOP_TRACKS = "music/artists/top_tracks";
  var PLAY_MEDIA = "player_queues/play_media";
  var CHART_LIMIT = 8;
  var PENDING_MS = 4000;
  var PLAY_RETRY_MS = 50;
  var PLAY_RETRY_LIMIT = 60;
  var SECTION_TITLE = "top tracks";
  var PLAY_TARGET =
    ".listitem-media-thumb.is-playable, button.listitem-mobile-play, .track-number-play.is-playable";

  function chartFromItems(items) {
    if (!Array.isArray(items)) return null;
    var names = [];
    var uris = [];
    for (var i = 0; i < items.length; i++) {
      var item = items[i];
      if (!item || typeof item.uri !== "string" || !item.uri) continue;
      names.push(typeof item.name === "string" ? item.name : "");
      uris.push(item.uri);
    }
    if (!uris.length) return null;
    return { names: names, uris: uris };
  }

  function createChartBook() {
    var charts = [];
    return {
      add: function (items) {
        var chart = chartFromItems(items);
        if (!chart) return;
        var key = chart.uris.join("\n");
        charts = charts.filter(function (existing) {
          return existing.uris.join("\n") !== key;
        });
        charts.push(chart);
        if (charts.length > CHART_LIMIT) charts.shift();
      },
      match: function (visibleNames) {
        if (!visibleNames || !visibleNames.length) return null;
        for (var i = charts.length - 1; i >= 0; i--) {
          var chart = charts[i];
          if (chart.names.length < visibleNames.length) continue;
          var same = true;
          for (var n = 0; n < visibleNames.length; n++) {
            if (chart.names[n] !== visibleNames[n]) {
              same = false;
              break;
            }
          }
          if (same) return chart;
        }
        return null;
      },
    };
  }

  function createTopTracksSession(book) {
    var latestId = null;
    var partial = [];
    return {
      outgoing: function (message) {
        if (!message || message.command !== TOP_TRACKS) return;
        latestId = String(message.message_id);
        partial = [];
      },
      incoming: function (message) {
        if (!message || latestId == null || String(message.message_id) !== latestId) {
          return;
        }
        if (message.error_code != null) return;
        var chunk = Array.isArray(message.result) ? message.result : [];
        if (message.partial) {
          partial = partial.concat(chunk);
          return;
        }
        book.add(partial.concat(chunk));
        partial = [];
      },
    };
  }

  function mediaUri(media) {
    if (typeof media === "string") return media;
    if (Array.isArray(media)) {
      return media.length === 1 ? mediaUri(media[0]) : null;
    }
    if (media && typeof media === "object" && typeof media.uri === "string") {
      return media.uri;
    }
    return null;
  }

  function copyPlayArgs(args) {
    var next = {};
    if (!args) return next;
    for (var key in args) {
      if (Object.prototype.hasOwnProperty.call(args, key)) next[key] = args[key];
    }
    return next;
  }

  /**
   * Return play_media args that queue ``uris`` in order, or null to send the
   * original command. A single track is already what the app asked to play.
   * The app's enqueue option is kept, so a track play still inserts.
   */
  function rewritePlayArgs(args, uris) {
    if (!args || !uris || uris.length < 2) return null;
    if (mediaUri(args.media) !== uris[0]) return null;
    var next = copyPlayArgs(args);
    next.media = uris.slice();
    next.shuffle = false;
    return next;
  }

  /**
   * Play-all args. The chart replaces the queue, the way an album play does.
   *
   * A track play uses the track enqueue option (``play``), which inserts
   * after the current item and keeps the rest of the queue. Album play uses
   * ``replace``, which swaps the queue for the new items. Return null when
   * this command is not that chart, so the app's command is sent unchanged.
   */
  function rewritePlayAllArgs(args, uris) {
    if (!args || !uris || !uris.length) return null;
    var uri = mediaUri(args.media);
    if (!uri || uris.indexOf(uri) < 0) return null;
    var next = copyPlayArgs(args);
    next.media = uris.slice();
    next.shuffle = false;
    next.option = "replace";
    delete next.start_item;
    return next;
  }

  function install() {
    if (window.__lastfmLocalTopTracksPlay) return;
    window.__lastfmLocalTopTracksPlay = true;

    var book = createChartBook();
    var session = createTopTracksSession(book);
    var pending = null;
    var suppressArm = false;
    var recent = [];
    var generation = 0;
    var nativeAdd = book.add.bind(book);

    // The exported book matches a visible prefix. This page also has to play
    // while the rows are hidden, and a later sort is not chart order. Keep
    // the charts for the request that is in flight, newest last.
    book.add = function (items) {
      nativeAdd(items);
      var chart = chartFromItems(items);
      if (!chart) return;
      chart.generation = generation;
      var key = chart.uris.join("\n");
      recent = recent.filter(function (existing) {
        return existing.uris.join("\n") !== key;
      });
      recent.push(chart);
      if (recent.length > CHART_LIMIT) recent.shift();
    };

    function parseMessage(data) {
      if (typeof data !== "string" || data.charAt(0) !== "{") return null;
      try {
        return JSON.parse(data);
      } catch (err) {
        return null;
      }
    }

    function trimEnds(text) {
      return (text || "").replace(/^\s+|\s+$/g, "");
    }

    function normalizeTitle(text) {
      return trimEnds(text).replace(/\s+/g, " ").toLowerCase();
    }

    // The listing's own toolbar, not a toolbar that belongs to a nested section.
    function ownToolbar(section) {
      var children = section.children;
      if (!children) return null;
      for (var i = 0; i < children.length; i++) {
        var child = children[i];
        if (child.classList && child.classList.contains("v-toolbar")) return child;
      }
      return null;
    }

    function sectionTitle(section) {
      var toolbar = ownToolbar(section);
      if (!toolbar) return "";
      var title = toolbar.querySelector(".v-toolbar-title");
      if (!title) return "";
      var button = title.querySelector("button");
      if (button) return normalizeTitle(button.textContent);
      var wrapper = title.querySelector(".toolbar-title-wrapper") || title;
      var text = "";
      for (var i = 0; i < wrapper.childNodes.length; i++) {
        var child = wrapper.childNodes[i];
        if (child.nodeType === 1) {
          if (child.classList && child.classList.contains("toolbar-subtitle")) break;
          continue;
        }
        if (child.nodeType === 3) text += child.nodeValue;
      }
      return normalizeTitle(text);
    }

    function isTopTracks(section) {
      return sectionTitle(section) === SECTION_TITLE;
    }

    // Vuetify's title is an outer .v-list-item-title. The slot inside it is
    // another .v-list-item-title, and the name is that inner element's first
    // text node. A following span is the version or the year. Read from the
    // inside out so a flat title still works.
    function rowTitle(row) {
      var titles = row.querySelectorAll(".v-list-item-title");
      for (var t = titles.length - 1; t >= 0; t--) {
        var title = titles[t];
        for (var i = 0; i < title.childNodes.length; i++) {
          var child = title.childNodes[i];
          if (child.nodeType !== 3) continue;
          var text = trimEnds(child.nodeValue);
          if (text) return text;
        }
      }
      return "";
    }

    function hasTrackRows(section) {
      var items = section.querySelectorAll(".v-list-item");
      for (var i = 0; i < items.length; i++) {
        if (items[i].closest("section") === section) return true;
      }
      return false;
    }

    function namedRows(section) {
      var rows = [];
      var items = section.querySelectorAll(".v-list-item");
      for (var i = 0; i < items.length; i++) {
        var row = items[i];
        if (row.closest("section") !== section) continue;
        if (rowTitle(row)) rows.push(row);
      }
      return rows;
    }

    function visibleNames(section) {
      return namedRows(section).map(function (row) {
        return rowTitle(row);
      });
    }

    function playTarget(row) {
      return row.querySelector(PLAY_TARGET);
    }

    function topSections() {
      return Array.prototype.filter.call(document.querySelectorAll("section"), isTopTracks);
    }

    // Bind a heading to the request generation that is current the first time
    // it is on screen. A chart from an older request, such as the previous
    // artist, does not belong to a heading first seen later.
    function rememberSection(section) {
      if (!section.getAttribute("data-lastfm-seen")) {
        section.setAttribute("data-lastfm-seen", String(generation));
      }
    }

    function chartsFor(section) {
      var seen = Number(section.getAttribute("data-lastfm-seen"));
      if (seen !== seen) seen = 0;
      var out = [];
      for (var i = recent.length - 1; i >= 0; i--) {
        if (recent[i].generation >= seen) out.push(recent[i]);
      }
      return out;
    }

    // Every visible name has to be on the chart. Order does not matter, so a
    // name sort still counts. Repeated names are consumed one at a time.
    function chartCovers(chart, names) {
      var pool = chart.names.slice();
      for (var i = 0; i < names.length; i++) {
        var at = pool.indexOf(names[i]);
        if (at < 0) return false;
        pool.splice(at, 1);
      }
      return true;
    }

    function matchVisible(section, names) {
      var charts = chartsFor(section);
      for (var i = 0; i < charts.length; i++) {
        if (!names.length || chartCovers(charts[i], names)) return charts[i];
      }
      return null;
    }

    // A heading with no rows is collapsed or still loading, so keep Play all.
    // Hide it only once real rows are a list this chart does not cover.
    function hideButton(section, names) {
      if (!names.length) return false;
      if (!chartsFor(section).length) return false;
      return !matchVisible(section, names);
    }

    function ensureButtons() {
      Array.prototype.forEach.call(topSections(), function (section) {
        rememberSection(section);
        var toolbar = ownToolbar(section);
        var button = toolbar && toolbar.querySelector(".lastfm-local-play-chart");
        var names = visibleNames(section);
        if (hideButton(section, names)) {
          if (button) button.remove();
          return;
        }
        if (button || !toolbar) return;
        var append = toolbar.querySelector(".v-toolbar__append");
        var host = append || toolbar;
        button = document.createElement("button");
        button.type = "button";
        button.className = "lastfm-local-play-chart";
        button.textContent = "Play all";
        button.setAttribute("aria-label", "Play top tracks");
        button.style.cssText = [
          "flex:none",
          "margin-right:12px",
          "border:0",
          "background:none",
          "padding:0",
          "font:inherit",
          "font-size:13px",
          "font-weight:500",
          "color:rgb(var(--v-theme-primary))",
          "cursor:pointer",
          "align-self:center",
          "white-space:nowrap",
        ].join(";");
        button.addEventListener("click", onPlayAll);
        if (append) append.insertBefore(button, append.firstChild);
        else host.appendChild(button);
      });
    }

    function kick(section) {
      var chart = matchVisible(section, visibleNames(section));
      if (!chart) return false;
      var rows = namedRows(section);
      var play = null;
      for (var i = 0; i < rows.length; i++) {
        play = playTarget(rows[i]);
        if (play) break;
      }
      if (!play) return false;
      pending = {
        uris: chart.uris.slice(),
        fromStart: true,
        until: Date.now() + PENDING_MS,
      };
      suppressArm = true;
      try {
        play.click();
      } finally {
        suppressArm = false;
      }
      return true;
    }

    function onPlayAll(event) {
      event.preventDefault();
      event.stopPropagation();
      var section = event.currentTarget.closest("section");
      if (!section || !isTopTracks(section)) return;
      if (kick(section)) return;
      // Open a collapsed section once. The other append button toggles, so
      // clicking it while rows are already on screen would close the list.
      if (!hasTrackRows(section)) {
        var toolbar = ownToolbar(section);
        var append = toolbar && toolbar.querySelector(".v-toolbar__append");
        var host = append || toolbar;
        if (host) {
          var buttons = host.querySelectorAll("button");
          for (var i = 0; i < buttons.length; i++) {
            if (!buttons[i].classList.contains("lastfm-local-play-chart")) {
              buttons[i].click();
              break;
            }
          }
        }
      }
      var tries = 0;
      function retry() {
        if (section.isConnected === false) return;
        if (kick(section)) return;
        tries += 1;
        if (tries >= PLAY_RETRY_LIMIT) return;
        setTimeout(retry, PLAY_RETRY_MS);
      }
      setTimeout(retry, PLAY_RETRY_MS);
    }

    document.addEventListener(
      "click",
      function (event) {
        if (suppressArm) return;
        var target = event.target;
        if (!target || !target.closest) return;
        if (target.closest(".lastfm-local-play-chart")) return;
        var play = target.closest(PLAY_TARGET);
        if (!play) return;
        var row = play.closest(".v-list-item");
        if (!row) return;
        var section = row.closest("section");
        if (!section || !isTopTracks(section)) return;
        var chart = matchVisible(section, visibleNames(section));
        if (!chart) return;
        var index = chart.names.indexOf(rowTitle(row));
        if (index < 0) return;
        pending = {
          uris: chart.uris.slice(index),
          fromStart: false,
          until: Date.now() + PENDING_MS,
        };
      },
      true,
    );

    var observer = new MutationObserver(function () {
      ensureButtons();
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
    ensureButtons();

    var NativeWebSocket = window.WebSocket;
    function WrappedWebSocket(url, protocols) {
      var socket =
        arguments.length > 1
          ? new NativeWebSocket(url, protocols)
          : new NativeWebSocket(url);
      hookSocket(socket);
      return socket;
    }
    WrappedWebSocket.prototype = NativeWebSocket.prototype;
    WrappedWebSocket.CONNECTING = NativeWebSocket.CONNECTING;
    WrappedWebSocket.OPEN = NativeWebSocket.OPEN;
    WrappedWebSocket.CLOSING = NativeWebSocket.CLOSING;
    WrappedWebSocket.CLOSED = NativeWebSocket.CLOSED;
    window.WebSocket = WrappedWebSocket;

    function hookSocket(socket) {
      var nativeSend = socket.send.bind(socket);
      socket.send = function (data) {
        try {
          data = rewriteOutgoing(data);
        } catch (err) {
          // A bad payload still has to reach the server unchanged.
        }
        return nativeSend(data);
      };
      socket.addEventListener("message", function (event) {
        try {
          var message = parseMessage(event.data);
          if (!message) return;
          Array.prototype.forEach.call(topSections(), rememberSection);
          session.incoming(message);
          ensureButtons();
        } catch (err) {
          // Leave the app's own handler to read the message.
        }
      });
    }

    function rewriteOutgoing(data) {
      var message = parseMessage(data);
      if (!message) return data;
      if (message.command === TOP_TRACKS) {
        generation += 1;
        recent = [];
      }
      session.outgoing(message);
      if (pending && Date.now() > pending.until) pending = null;
      if (message.command !== PLAY_MEDIA || !pending) return data;
      if (pending.fromStart) {
        var replaced = rewritePlayAllArgs(message.args, pending.uris);
        if (!replaced) return data;
        pending = null;
        message.args = replaced;
        return JSON.stringify(message);
      }
      var rewritten = rewritePlayArgs(message.args, pending.uris);
      if (!rewritten) return data;
      pending = null;
      message.args = rewritten;
      return JSON.stringify(message);
    }
  }

  return {
    chartFromItems: chartFromItems,
    createChartBook: createChartBook,
    createTopTracksSession: createTopTracksSession,
    mediaUri: mediaUri,
    rewritePlayArgs: rewritePlayArgs,
    rewritePlayAllArgs: rewritePlayAllArgs,
    install: install,
    TOP_TRACKS: TOP_TRACKS,
    PLAY_MEDIA: PLAY_MEDIA,
  };
});
