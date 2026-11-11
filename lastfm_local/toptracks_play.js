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

  /**
   * Return play_media args that queue ``uris`` in order, or null to send the
   * original command. A single track is already what the app asked to play.
   */
  function rewritePlayArgs(args, uris) {
    if (!args || !uris || uris.length < 2) return null;
    if (mediaUri(args.media) !== uris[0]) return null;
    var next = {};
    for (var key in args) {
      if (Object.prototype.hasOwnProperty.call(args, key)) next[key] = args[key];
    }
    next.media = uris.slice();
    next.shuffle = false;
    return next;
  }

  function install() {
    if (window.__lastfmLocalTopTracksPlay) return;
    window.__lastfmLocalTopTracksPlay = true;

    var book = createChartBook();
    var session = createTopTracksSession(book);
    var pending = null;

    function parseMessage(data) {
      if (typeof data !== "string" || data.charAt(0) !== "{") return null;
      try {
        return JSON.parse(data);
      } catch (err) {
        return null;
      }
    }

    function visibleNames(section) {
      return Array.prototype.map.call(
        section.querySelectorAll(".artist-top-tracks__name"),
        function (node) {
          return (node.textContent || "").trim();
        },
      );
    }

    function namedRows(section) {
      return Array.prototype.filter.call(
        section.querySelectorAll(".artist-top-tracks__track"),
        function (row) {
          return row.querySelector(".artist-top-tracks__name");
        },
      );
    }

    function ensureButtons() {
      var sections = document.querySelectorAll(".artist-top-tracks");
      Array.prototype.forEach.call(sections, function (section) {
        var chart = book.match(visibleNames(section));
        var button = section.querySelector(".lastfm-local-play-chart");
        if (!chart) {
          if (button) button.remove();
          return;
        }
        if (button) return;
        var head = section.querySelector(".artist-top-tracks__head");
        if (!head) return;
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
        ].join(";");
        button.addEventListener("click", onPlayAll);
        var more = head.querySelector(".artist-top-tracks__more");
        if (more) head.insertBefore(button, more);
        else head.appendChild(button);
      });
    }

    function arm(section, index) {
      var chart = book.match(visibleNames(section));
      if (!chart || index < 0 || index >= chart.uris.length) return;
      pending = { uris: chart.uris.slice(index), until: Date.now() + PENDING_MS };
    }

    function onPlayAll(event) {
      event.preventDefault();
      event.stopPropagation();
      var section = event.currentTarget.closest(".artist-top-tracks");
      if (!section) return;
      var playButton = section.querySelector(
        ".artist-top-tracks__track button:not(.artist-top-tracks__menu)",
      );
      if (!playButton) return;
      playButton.click();
    }

    document.addEventListener(
      "click",
      function (event) {
        var target = event.target;
        if (!target || !target.closest) return;
        if (target.closest(".lastfm-local-play-chart")) return;
        if (target.closest(".artist-top-tracks__menu")) return;
        var button = target.closest("button");
        var row = target.closest(".artist-top-tracks__track");
        if (!button || !row || !row.contains(button)) return;
        var section = row.closest(".artist-top-tracks");
        if (!section) return;
        var rows = namedRows(section);
        arm(section, Array.prototype.indexOf.call(rows, row));
      },
      true,
    );

    var observer = new MutationObserver(function () {
      ensureButtons();
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });

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
      session.outgoing(message);
      if (pending && Date.now() > pending.until) pending = null;
      if (message.command !== PLAY_MEDIA || !pending) return data;
      var args = rewritePlayArgs(message.args, pending.uris);
      if (!args) return data;
      pending = null;
      message.args = args;
      return JSON.stringify(message);
    }
  }

  return {
    chartFromItems: chartFromItems,
    createChartBook: createChartBook,
    createTopTracksSession: createTopTracksSession,
    mediaUri: mediaUri,
    rewritePlayArgs: rewritePlayArgs,
    install: install,
    TOP_TRACKS: TOP_TRACKS,
    PLAY_MEDIA: PLAY_MEDIA,
  };
});
