export {};

declare global {
  const CabosEngine: CabosEngine;
}

type Material = string;
type Constitution = string;
type BoardTypeId = string;
export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface Template {
  readonly id: string;
  readonly label: string;
  readonly description: string;
}

export interface State {
  proj: string;
  loc: string;
  tair: number;
  tsoil: number;
  rsolo: number;
  isol: string;
  mat: Material;
  alThr: number;
  alPmin: number;
  limT: number;
  lim: number;
  folga: boolean;
  cos: number;
  descABB: number;
  descHager: number;
  sc: ShortCircuitState;
  dc: DcState;
  invs: InverterState[];
  rInv: Route;
  percs: PercState[];
  gws: GatewayState[];
  obra: WorkData;
  icu: IcuCriteria;
  btypes?: Record<string, BoardTypeId>;
  pint?: number;
}

export interface ShortCircuitState {
  on: boolean;
  fonte: string;
  sn: number;
  ucc: number;
  scc: number;
  icc: number;
  L0: number;
  s0: number;
  m0: string;
  n0: number;
}

export interface DcState {
  tmin: number;
  tcell: number;
  lim: number;
  ifuse: number;
  f: number;
  sel: number;
  arr: JsonValue[];
}

export interface Route {
  ref: string;
  cons: Constitution;
  disp: string;
  trays: number;
  sol: boolean;
}

export interface InverterState {
  id?: number;
  modelo: string;
  pman: number;
  q: string;
  L: number;
  S: string;
  est?: string;
  cos?: number | null;
  cons?: Constitution;
}

export interface PercState extends Route {
  id?: number;
  orig: string;
  dest: string;
  L: number;
  S: string;
  extra?: number;
  split?: boolean;
  subs?: Record<string, { S: string }>;
}

export interface GatewayState {
  id?: number;
  nome: string;
  modelo: string;
  fases: number;
  In: number;
  dimNom?: boolean;
}

export interface WorkData {
  cliente: string;
  morada: string;
  desenho: string;
  estado: string;
  rev: string;
  aprov: Approval | null;
  track?: JsonValue;
  trackUpd?: string;
}

export interface Approval {
  id: string;
  nome: string;
  em: string;
}

export interface IcuCriteria {
  modo: string;
  icc: number;
  sn: number;
}

export interface Result {
  invC: ResultCircuit[];
  pC: ResultCircuit[];
  costTot: number;
  termTot: number;
  costEst: boolean;
  Ptot: number;
  IbTot: number;
  ikSrc: number;
  icuOn: boolean;
  central: CentralProtection[];
  brkTot: number;
}

export interface CentralProtection {
  node: string;
  k: number;
  n: number;
}

export interface ResultCircuit {
  cos: number | null;
  ref: JsonObject;
  kind: 'inv' | 'perc';
  nome: string;
  modelo?: string;
  para?: string;
  base?: JsonObject;
  sub?: JsonObject;
  split?: boolean;
  forceIn?: number;
  p: number;
  Ib: number;
  IbInv?: number;
  iac?: number;
  ibSrc?: string;
  fases: number;
  loaded: number;
  L: number;
  r: Route | JsonObject;
  consForced?: boolean;
  ti: TemperatureInfo;
  nAgr: number;
  path: JsonObject[];
  zUp: Impedance | null;
  Lc: number;
  opts: CableOption[];
  noFit: boolean;
  dropMsg: string | null;
  auto: boolean;
  i: number;
  min: number;
  res: CalculatedCable | null;
  acc: number;
  cost: Cost | null;
  alt: Alternative | null;
  term: TerminalCost | null;
  noFitMsg: string | null;
  code: string;
  gw?: GatewayState | null;
  gwErr?: string;
  nInv?: number;
  sel?: Selectivity | null;
  _j?: number;
}

export interface TemperatureInfo {
  buried: boolean;
  t: number;
  ft: number | null;
  fsolo: number;
  ftubo: number;
  src: string;
}

export interface Impedance {
  R: number;
  X: number;
}

export interface CableOption {
  n: number;
  s: number;
  mat: Material;
  cons: Constitution;
}

export interface CalculatedCable extends CableOption {
  Iz: number;
  iz0: number;
  q: string;
  qcol: number;
  fg: number | null;
  fgSrc: string;
  f: number;
  nEff: number;
  perTray: number;
  trays: number;
  In: number;
  I2: number;
  du: number;
  term: boolean;
  sob: boolean;
  brk: Breaker | null;
  scOk: boolean;
  ikmax?: number;
  ikmin?: number;
  Im?: number;
  elec?: boolean;
  Iset?: number | null;
  trip?: boolean;
  therm?: boolean;
  i2t?: number;
  k2s2?: number;
  icuOk?: boolean;
  icuAlt?: Breaker | null;
}

export interface Breaker {
  s: string;
  icu: number;
  ref: string;
  d: string;
  p: number;
  k2: number;
  mod: boolean;
  dif?: Differential | null;
  reg?: number | null;
  icuOk: boolean;
  name: string;
}

export interface Differential {
  name: string;
  refs: string[];
  p: number;
  central?: boolean;
  tor?: Toroid;
}

export interface Toroid {
  d: number;
  ref: string;
  p: number;
  need: number;
}

export interface Selectivity {
  In: number;
  dn: number;
  code: string;
  k: number;
}

export interface Cost {
  v: number;
  est: boolean;
}

export interface TerminalCost {
  v: number;
  est: boolean;
}

export interface Alternative {
  v: number;
  est: boolean;
  o: CalculatedCable;
}

export interface Summary {
  inverters: number;
  powerKW: number;
  currentA: number;
  connectionBreakerA: number | null;
  connectionBreaker: { ratingA: number; code: string | null } | null;
  maxVoltageDropPct: number;
  maxVoltageDrop: number;
  shortCircuit: { verified: boolean; currentKA: number | null };
  cables: number;
  terminals: number;
  cablesAndTerminals: number;
  protectionCost: number;
  reviewCount: number;
  estimated: boolean;
}

export interface Catalogs {
  readonly inverters: readonly InverterCatalog[];
  readonly panels: readonly PanelCatalog[];
  readonly gateways: readonly GatewayCatalog[];
  readonly regions: readonly RegionCatalog[];
  readonly installModes: readonly InstallModeCatalog[];
  readonly materials: readonly SelectOption[];
  readonly insulations: readonly SelectOption[];
  readonly constitutions: readonly SelectOption[];
  readonly dispositions: readonly SelectOption[];
  readonly boardTypes: Readonly<Record<string, readonly [string, string]>>;
  readonly soilResistivities: readonly (readonly [number, number, string])[];
  readonly installModeImage: (id: string) => readonly string[] | null;
}

export interface InverterCatalog {
  marca: string;
  modelo: string;
  pnom: number;
  pmax: number;
  iac: number;
  iacmax: number;
  fases: number;
  mppt?: number;
  cc?: number;
  imax?: number;
  isc?: number;
  vmax?: number;
  vstart?: number;
  vmppmin?: number;
  vmppmax?: number;
  conf?: boolean;
}

export interface PanelCatalog {
  marca: string;
  modelo: string;
  pmax: number | null;
  cel: number | null;
  vmp: number | null;
  imp: number | null;
  voc: number | null;
  isc: number | null;
  kvoc: number | null;
  kisc: number | null;
  kp: number | null;
  ef: number | null;
}

export interface GatewayCatalog {
  marca: string;
  modelo: string;
  gama: string;
  fases: number;
  In: number;
  P: number;
  ports: number;
  portI: number;
  base: boolean;
}

export interface RegionCatalog {
  id: string;
  label: string;
  tair: number;
  tsoil: number;
  tmin: number;
}

export interface InstallModeCatalog {
  id: string;
  label: string;
  description: string;
  method: string;
  group: string;
  imageId: string;
}

export interface SelectOption {
  id: string;
  label: string;
}

export interface BoardsView {
  boards: BoardView[];
}

export interface BoardView {
  node: string;
  role: string;
  isEnd: boolean;
  inputs: BoardCircuitBrief[];
  output: BoardCircuitBrief | null;
  aparelhagem: BoardDevice[];
  devices: BoardDevice[];
  cabos: BoardCable[];
  cables: BoardCable[];
  envolventeMinima: Enclosure | null;
  minimumEnclosure: Enclosure | null;
  notes: string[];
  difficulty: number;
  currentA: number;
  modules: number;
  freeCableZoneMm: number;
  glandWidthMm: number;
  components: JsonValue;
}

export interface BoardCircuitBrief {
  code: string | null;
  kind: string;
  name: string;
  Ib: number;
  In: number;
}

export interface BoardDevice {
  nome: string;
  txt: string;
  dif: string;
}

export interface BoardCable {
  nome: string;
  cabo: string;
  D: number;
  r: number;
  nCond: number;
  mat: string;
  s: number;
  n: number;
  cap: number;
  multi: boolean;
}

export interface Enclosure {
  ref: string;
  heightMm: number;
  widthMm: number;
  depthMm: number;
  area: number;
  rows: JsonValue[];
  mountingRows: number;
  modulesPerRow: number;
  cableRows: number;
}

export interface CircuitRow {
  code: string | null;
  kind: string;
  designation: string;
  origin: string;
  destination: string;
  origem: string;
  destino: string;
  lengthM: number;
  L: number;
  calculationLengthM: number;
  sectionMm2: number | null;
  section: string | null;
  cable: CircuitCable | null;
  Iz: number | null;
  In: number | null;
  I2: number | null;
  voltageDropV: number | null;
  voltageDropPct: number | null;
  deltaU: number | null;
  breaker: RowBreaker | null;
  disjuntor: RowBreaker | null;
  route: RouteCard | null;
  verdict: 'ok' | 'a rever';
  veredicto: 'ok' | 'a rever';
  message: string;
  reason: string;
}

export interface CircuitCable {
  material: string;
  conductors: number;
  sectionMm2: number;
  constitution: string;
  phase: string | null;
  neutral: string | null;
  earth: string | null;
  text: string;
}

export interface RowBreaker {
  name: string | null;
  ref: string | null;
  ratingA: number;
  icuKA?: number;
  poles: number;
  differential: { name: string; refs: string[] } | null;
}

export interface RouteCard {
  ref: string;
  method: string | null;
  description: string;
  constitution: string;
  disposition: string;
  trays: number;
  exposedToSun: boolean;
  temperature: TemperatureInfo;
  circuits: number;
  perTray: number;
  factor: number | null;
  factorSource: string;
}

export interface InverterPatch {
  id: number;
  field?: string;
  value?: JsonValue;
  patch?: { [field: string]: JsonValue };
}
export interface PercPatch {
  id: number | string;
  field?: string;
  value?: JsonValue;
  patch?: { [field: string]: JsonValue };
}
export interface GatewayPatch {
  id: number;
  field?: string;
  value?: JsonValue;
  patch?: { [field: string]: JsonValue };
}
export interface CriteriaPatch {
  field?: string;
  value?: JsonValue;
  loc?: string; rsolo?: number; isol?: 'XLPE' | 'PVC'; mat?: 'auto' | 'Cu' | 'Al';
  alThr?: number; alPmin?: number; limT?: number; lim?: number; folga?: boolean;
  cos?: number; descABB?: number; descHager?: number; pint?: number | null;
  icu?: Partial<IcuCriteria>;
}
export interface BoardActionArgs {
  type: 'INT' | 'CONT' | 'GW' | 'CLI'; name?: string; position?: number | string;
  L?: number; modelo?: string; dimNom?: boolean;
}
export interface ExportFile { blob: Blob; filename: string; }
export interface PersistedCircuit { code: string; name: string; review: boolean; note?: string; }
export interface PersistedTotals { circuits: number; review: number; inverters: number; kw_ac?: number; }
export interface PersistedResult { format: 1; engine_version: string; circuits: PersistedCircuit[]; totals: PersistedTotals; }
export interface VariantSummary {
  cables: number; terminals: number; cablesAndTerminals: number; protection: number;
  total: number; maxVoltageDropPct: number; differentCables: number; review: number;
  estimated: boolean; aluminum: number; circuits: number;
}
export interface Variant { id: string; label: string; note: string; summary: VariantSummary | null; error: string | null; }
export interface Actions {
  addInverter(state: State, args?: JsonObject): State;
  removeInverter(state: State, args: { id: number }): State;
  duplicateInverter(state: State, args: { id: number }): State;
  setInverterField(state: State, args: InverterPatch): State;
  updateInverter(state: State, args: InverterPatch): State;
  setInverterModel(state: State, args: InverterPatch): State;
  setInverterPman(state: State, args: InverterPatch): State;
  setInverterBoard(state: State, args: InverterPatch): State;
  setInverterLength(state: State, args: InverterPatch): State;
  setInverterSection(state: State, args: InverterPatch): State;
  setInverterRoute(state: State, args: JsonObject): State;
  addPerc(state: State, args?: JsonObject): State;
  removePerc(state: State, args: { id: number }): State;
  setPercField(state: State, args: PercPatch): State;
  updatePerc(state: State, args: PercPatch): State;
  setPercOrigin(state: State, args: PercPatch): State;
  setPercDestination(state: State, args: PercPatch): State;
  setPercSection(state: State, args: PercPatch): State;
  setPercRoute(state: State, args: PercPatch): State;
  addGateway(state: State, args?: JsonObject): State;
  removeGateway(state: State, args: { id: number }): State;
  renameGateway(state: State, args: GatewayPatch): State;
  configureGateway(state: State, args: GatewayPatch): State;
  updateGateway(state: State, args: GatewayPatch): State;
  addBoard(state: State, args: BoardActionArgs): State;
  setBoardType(state: State, args: { name: string; type: BoardTypeId | null }): State;
  setCriteria(state: State, args: CriteriaPatch): State;
  setCriterion(state: State, args: CriteriaPatch): State;
  setIcu(state: State, args: Partial<IcuCriteria>): State;
  setWorkData(state: State, args: JsonObject): State;
  setProject(state: State, project: string | { proj: string }): State;
  applyTemplate(state: State, templateId: string): State;
  resetExample(state: State): State;
  addPath(state: State, args?: JsonObject): State;
  removePath(state: State, args: { id: number }): State;
  setPathField(state: State, args: PercPatch): State;
  updatePath(state: State, args: PercPatch): State;
  setPathRoute(state: State, args: PercPatch): State;
  chooseInverterModel(state: State, args: InverterPatch): State;
  setGatewayField(state: State, args: GatewayPatch): State;
}
export interface Exports {
  reportPdf(state: State, result: Result): Promise<ExportFile>;
  reportDocx(state: State, result: Result): Promise<ExportFile>;
  bomPdf(state: State, result: Result): Promise<ExportFile>;
  sldSvg(state: State, result: Result): Promise<ExportFile>;
  sldPng(state: State, result: Result): Promise<ExportFile>;
  sldDxf(state: State, result: Result): Promise<ExportFile>;
  copyTable(state: State, result: Result): string;
}
export interface Compare { variants(state: State): Variant[]; apply(state: State, variantId: string): State; }

export interface CabosEngine {
  readonly protocol: 1;
  readonly engine_version: string;
  newState(templateId?: string): State;
  readonly templates: readonly Template[];
  migrate(raw: JsonValue): State;
  solve(state: State): { state: State; result: Result };
  summarize(result: Result, state?: State): Summary;
  readonly catalogs: Catalogs;
  installModeImage(id: string): readonly string[] | null;
  readonly views: {
    sld(state: State, result: Result): string;
    boards(state: State, result: Result): BoardsView;
    circuitRows(state: State, result: Result): CircuitRow[];
  };
  readonly actions: Actions;
  readonly persistedResult: (state: State, result: Result) => PersistedResult;
  readonly exports: Exports;
  readonly compare: Compare;
}
