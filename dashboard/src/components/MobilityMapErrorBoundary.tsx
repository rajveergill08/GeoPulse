import {Component, type ReactNode} from 'react';

import type {CannibalizationFlow, DashboardSnapshot} from '../data/types';
import {MobilityMapUnavailable} from './MobilityMapUnavailable';

interface MobilityMapErrorBoundaryProps {
  snapshot: DashboardSnapshot;
  flow: CannibalizationFlow;
  selectedHour: number;
  isPlaying: boolean;
  children: ReactNode;
}

interface MobilityMapErrorBoundaryState {
  hasError: boolean;
}

export class MobilityMapErrorBoundary extends Component<
  MobilityMapErrorBoundaryProps,
  MobilityMapErrorBoundaryState
> {
  state: MobilityMapErrorBoundaryState = {hasError: false};

  static getDerivedStateFromError(): MobilityMapErrorBoundaryState {
    return {hasError: true};
  }

  render() {
    if (this.state.hasError) {
      const {snapshot, flow, selectedHour, isPlaying} = this.props;
      return (
        <MobilityMapUnavailable
          snapshot={snapshot}
          flow={flow}
          selectedHour={selectedHour}
          isPlaying={isPlaying}
        />
      );
    }

    return this.props.children;
  }
}
