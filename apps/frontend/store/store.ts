import { configureStore } from "@reduxjs/toolkit";
import { gatewayApi } from "./gateway-api";
import realtime from "./realtime-slice";
import ui from "./ui-slice";
import sandboxLab from "./sandbox-lab-slice";

export const makeStore = () => configureStore({
  reducer: {
    [gatewayApi.reducerPath]: gatewayApi.reducer,
    realtime,
    ui,
    sandboxLab,
  },
  middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(gatewayApi.middleware),
});

export type AppStore = ReturnType<typeof makeStore>;
export type RootState = ReturnType<AppStore["getState"]>;
export type AppDispatch = AppStore["dispatch"];
