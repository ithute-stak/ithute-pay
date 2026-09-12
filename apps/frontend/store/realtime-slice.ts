import { createSlice, type PayloadAction } from "@reduxjs/toolkit";

export type RealtimeState = {
  connected: boolean;
  lastEvent?: { type: string; data?: unknown; at: string };
  unread: number;
};

const initialState: RealtimeState = { connected: false, unread: 0 };

const realtimeSlice = createSlice({
  name: "realtime",
  initialState,
  reducers: {
    setConnected(state, action: PayloadAction<boolean>) { state.connected = action.payload; },
    receiveEvent(state, action: PayloadAction<{ type: string; data?: unknown }>) {
      state.lastEvent = { ...action.payload, at: new Date().toISOString() };
      state.unread += 1;
    },
    clearUnread(state) { state.unread = 0; },
  },
});

export const { setConnected, receiveEvent, clearUnread } = realtimeSlice.actions;
export default realtimeSlice.reducer;
