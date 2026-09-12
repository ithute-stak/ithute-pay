import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import type { ProviderId } from "@/lib/provider-workspaces";

export type DocumentationTab = "admin" | "consumer" | "testing";

export type UiState = {
  sidebarCollapsed: boolean;
  documentationTab: DocumentationTab;
  selectedProvider: ProviderId | null;
};

const initialState: UiState = {
  sidebarCollapsed: false,
  documentationTab: "admin",
  selectedProvider: null,
};

const uiSlice = createSlice({
  name: "ui",
  initialState,
  reducers: {
    setSidebarCollapsed(state, action: PayloadAction<boolean>) {
      state.sidebarCollapsed = action.payload;
    },
    toggleSidebar(state) {
      state.sidebarCollapsed = !state.sidebarCollapsed;
    },
    setDocumentationTab(state, action: PayloadAction<DocumentationTab>) {
      state.documentationTab = action.payload;
    },
    setSelectedProvider(state, action: PayloadAction<ProviderId | null>) {
      state.selectedProvider = action.payload;
    },
  },
});

export const {
  setSidebarCollapsed,
  toggleSidebar,
  setDocumentationTab,
  setSelectedProvider,
} = uiSlice.actions;
export default uiSlice.reducer;
