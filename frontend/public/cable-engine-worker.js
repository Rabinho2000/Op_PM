// Web Worker do motor de cabos (M2). Ficheiro ESTÁTICO servido tal e qual
// (frontend/public -> /cable-engine-worker.js): a página cria-o com
// `new Worker("/cable-engine-worker.js")` e envia-lhe o script do motor (privado,
// vindo da API, já com o SHA-256 verificado) numa mensagem `init`.
//
// Isolamento:
//  - o worker não tem DOM, sessionStorage/localStorage (tokens MSAL) nem acesso
//    a nada da página; só comunica por mensagens validadas (ver
//    src/features/cables/engineWorker/protocol.ts);
//  - o nginx serve ESTE ficheiro com a sua própria CSP (docker/nginx*.conf):
//    `connect-src 'none'` (sem rede, imposto pelo browser) e 'unsafe-eval' só
//    aqui, para o motor poder ser executado com eval indireto sem abrir
//    'unsafe-eval' à aplicação;
//  - além disso, antes de executar o motor, retira-se ao worker a rede e o
//    armazenamento (defesa em profundidade, também vale fora do nginx);
//  - só se pode chamar o que o motor publica (lista fechada calculada no
//    arranque).
//
// Mensagens:
//   página -> worker  {source, protocol, type:"init", script}              (uma vez)
//                     {source, protocol, type:"call", id, path, args}
//   worker -> página  {source, protocol, type:"ready"|"result"|"error"|"fatal", ...}
(function () {
  "use strict";
  var scope = self;
  var post = scope.postMessage.bind(scope);
  var runScript = scope.eval; // eval indireto: executa o motor no âmbito global do worker
  var MAX_SCRIPT_CHARS = 9 * 1024 * 1024;

  var blocked = [
    "fetch", "XMLHttpRequest", "WebSocket", "EventSource", "WebTransport",
    "importScripts", "indexedDB", "caches", "BroadcastChannel",
    "Worker", "SharedWorker", "RTCPeerConnection", "localStorage", "sessionStorage"
  ];
  for (var b = 0; b < blocked.length; b += 1) {
    try {
      Object.defineProperty(scope, blocked[b], { value: undefined, writable: false, configurable: false });
    } catch (ignored) {
      // Já não é redefinível: a CSP do worker continua a ser a barreira.
    }
  }

  var SOURCE = "op-pm-cable-engine";
  var PROTOCOL = 1;
  var ROOT_METHODS = ["newState", "migrate", "solve", "summarize", "persistedResult"];
  var GROUPS = ["views", "actions", "exports", "compare"];
  var MAX_ARGS = 8;
  var has = Object.prototype.hasOwnProperty;
  var engine = null;
  var allowed = Object.create(null);
  var started = false;

  function send(message) {
    message.source = SOURCE;
    message.protocol = PROTOCOL;
    post(message);
  }

  function describe(reason, fallback) {
    var text = reason && typeof reason.message === "string" ? reason.message : (typeof reason === "string" ? reason : "");
    text = text.replace(/[\u0000-\u001f\u007f]+/g, " ").trim();
    return (text || fallback).slice(0, 300);
  }

  // Cópia só de dados (sem funções), para a mensagem `ready`.
  function plain(value, depth) {
    if (depth > 12) return null;
    if (value === null || typeof value === "string" || typeof value === "boolean" || typeof value === "number") return value;
    if (Array.isArray(value)) {
      var list = [];
      for (var i = 0; i < value.length; i += 1) list.push(typeof value[i] === "function" ? null : plain(value[i], depth + 1));
      return list;
    }
    if (typeof value === "object") {
      var copy = {};
      var keys = Object.keys(value);
      for (var k = 0; k < keys.length; k += 1) {
        var item = value[keys[k]];
        if (typeof item === "function" || item === undefined) continue;
        copy[keys[k]] = plain(item, depth + 1);
      }
      return copy;
    }
    return null;
  }

  function fail(message) {
    try { send({ type: "fatal", message: message }); } catch (ignored) { /* sem canal */ }
  }

  function isEnvelope(data, type) {
    return data && typeof data === "object" && !Array.isArray(data) &&
      data.source === SOURCE && data.protocol === PROTOCOL && data.type === type;
  }

  function isCall(data) {
    if (!isEnvelope(data, "call")) return false;
    if (typeof data.id !== "number" || !Number.isInteger(data.id) || data.id < 1) return false;
    if (!Array.isArray(data.path) || data.path.length < 1 || data.path.length > 2) return false;
    for (var i = 0; i < data.path.length; i += 1) if (typeof data.path[i] !== "string") return false;
    return Array.isArray(data.args) && data.args.length <= MAX_ARGS;
  }

  function start(script) {
    try {
      runScript(script);
    } catch (reason) {
      fail("Não foi possível executar a ferramenta de cálculo: " + describe(reason, "erro ao carregar"));
      return;
    }
    engine = scope.CabosEngine;
    try { delete scope.CabosEngine; } catch (ignored) { /* var global: continua inacessível à página */ }

    if (!engine || typeof engine !== "object") return fail("A ferramenta de cálculo não publicou CabosEngine.");
    if (engine.protocol !== PROTOCOL) return fail("Versão de protocolo da ferramenta de cálculo não suportada.");
    if (typeof engine.engine_version !== "string" || engine.engine_version.length === 0) {
      return fail("A ferramenta de cálculo não indica engine_version.");
    }

    // Lista fechada do que se pode chamar: "metodo" ou "grupo.metodo".
    var surface = { root: [], views: [], actions: [], exports: [], compare: [] };
    var r;
    for (r = 0; r < ROOT_METHODS.length; r += 1) {
      if (typeof engine[ROOT_METHODS[r]] === "function") {
        allowed[ROOT_METHODS[r]] = true;
        surface.root.push(ROOT_METHODS[r]);
      }
    }
    for (var g = 0; g < GROUPS.length; g += 1) {
      var group = engine[GROUPS[g]];
      if (!group || typeof group !== "object") continue;
      var names = Object.keys(group);
      for (var n = 0; n < names.length; n += 1) {
        if (typeof group[names[n]] === "function") {
          allowed[GROUPS[g] + "." + names[n]] = true;
          surface[GROUPS[g]].push(names[n]);
        }
      }
    }

    // Imagens dos modos de instalação: no motor é uma função; na página, dados.
    var images = {};
    var imageFn = typeof engine.installModeImage === "function"
      ? engine.installModeImage.bind(engine)
      : (engine.catalogs && typeof engine.catalogs.installModeImage === "function" ? engine.catalogs.installModeImage.bind(engine.catalogs) : null);
    var modes = engine.catalogs && Array.isArray(engine.catalogs.installModes) ? engine.catalogs.installModes : [];
    if (imageFn) {
      for (var m = 0; m < modes.length; m += 1) {
        var ids = [modes[m] && modes[m].id, modes[m] && modes[m].imageId];
        for (var q = 0; q < ids.length; q += 1) {
          if (typeof ids[q] !== "string" || has.call(images, ids[q])) continue;
          try { images[ids[q]] = plain(imageFn(ids[q]), 0); } catch (ignored) { images[ids[q]] = null; }
        }
      }
    }

    try {
      send({
        type: "ready",
        engine_version: engine.engine_version,
        templates: plain(engine.templates || [], 0),
        catalogs: plain(engine.catalogs || {}, 0),
        installModeImages: images,
        surface: surface
      });
    } catch (reason) {
      fail("Não foi possível iniciar a ferramenta de cálculo: " + describe(reason, "erro"));
    }
  }

  function handleCall(data) {
    var key = data.path.join(".");
    if (!allowed[key]) {
      send({ type: "error", id: data.id, message: "Operação desconhecida: " + key.slice(0, 80) });
      return;
    }
    var target = data.path.length === 2 ? engine[data.path[0]] : engine;
    var method = target[data.path[data.path.length - 1]];
    Promise.resolve()
      .then(function () { return method.apply(target, data.args); })
      .then(function (value) {
        try {
          send({ type: "result", id: data.id, value: value });
        } catch (reason) {
          send({ type: "error", id: data.id, message: "O resultado do motor não é transferível: " + describe(reason, "erro de clonagem") });
        }
      }, function (reason) {
        send({ type: "error", id: data.id, message: describe(reason, "Erro no motor de cálculo.") });
      });
  }

  scope.onmessage = function (event) {
    var data = event.data;
    if (!started) {
      if (isEnvelope(data, "init") && typeof data.script === "string" && data.script.length > 0 && data.script.length <= MAX_SCRIPT_CHARS) {
        started = true;
        start(data.script);
      }
      return;
    }
    if (engine && isCall(data)) handleCall(data);
  };
})();
