import keplerGlReducer, {
  enhanceReduxMiddleware,
  type KeplerGlState
} from '@kepler.gl/reducers';
import {applyMiddleware, combineReducers, compose, createStore} from 'redux';
import type {Reducer} from 'redux';

type KeplerGlStateMap = Record<string, Partial<KeplerGlState>>;
const typedKeplerGlReducer = keplerGlReducer as Reducer<KeplerGlStateMap>;

const rootReducer = combineReducers({
  keplerGl: typedKeplerGlReducer
});

const middleware = enhanceReduxMiddleware([]);

export const store = createStore(rootReducer, {}, compose(applyMiddleware(...middleware)));

export type RootState = ReturnType<typeof rootReducer>;
export type AppDispatch = typeof store.dispatch;
