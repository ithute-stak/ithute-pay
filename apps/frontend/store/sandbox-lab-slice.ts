import { createSlice, type PayloadAction } from "@reduxjs/toolkit";

export type SandboxScenario = "success" | "insufficient_funds" | "processing";
export type SandboxExecutionMode = "simulator" | "live_sandbox";

export type SandboxLabState = {
  selectedProduct: string;
  scenario: SandboxScenario;
  executionMode: SandboxExecutionMode;
  amount: string;
  currency: string;
  phone: string;
  receiverPartyCode: string;
  recentResults: Array<{
    run_id?: string;
    product: string;
    passed: boolean;
    status?: string;
    executed_at?: string;
    result?: unknown;
  }>;
};

const initialState: SandboxLabState = {
  selectedProduct: "collection",
  scenario: "success",
  executionMode: "live_sandbox",
  amount: "25.00",
  currency: "LSL",
  phone: "",
  receiverPartyCode: "000001",
  recentResults: [],
};

const sandboxLabSlice = createSlice({
  name: "sandboxLab",
  initialState,
  reducers: {
    selectSandboxProduct(state, action: PayloadAction<string>) {
      state.selectedProduct = action.payload;
      state.scenario = "success";
    },
    setSandboxScenario(state, action: PayloadAction<SandboxScenario>) {
      state.scenario = action.payload;
    },
    setSandboxExecutionMode(state, action: PayloadAction<SandboxExecutionMode>) {
      state.executionMode = action.payload;
    },
    setSandboxAmount(state, action: PayloadAction<string>) {
      state.amount = action.payload;
    },
    setSandboxCurrency(state, action: PayloadAction<string>) {
      state.currency = action.payload.toUpperCase();
    },
    setSandboxPhone(state, action: PayloadAction<string>) {
      state.phone = action.payload;
    },
    setSandboxReceiverPartyCode(state, action: PayloadAction<string>) {
      state.receiverPartyCode = action.payload;
    },
    recordSandboxResult(state, action: PayloadAction<SandboxLabState["recentResults"][number]>) {
      state.recentResults = [action.payload, ...state.recentResults].slice(0, 100);
    },
    clearSandboxResults(state) {
      state.recentResults = [];
    },
  },
});

export const {
  selectSandboxProduct,
  setSandboxScenario,
  setSandboxExecutionMode,
  setSandboxAmount,
  setSandboxCurrency,
  setSandboxPhone,
  setSandboxReceiverPartyCode,
  recordSandboxResult,
  clearSandboxResults,
} = sandboxLabSlice.actions;
export default sandboxLabSlice.reducer;
