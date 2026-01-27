/**
 * Strategy Performance Chart Component
 * 
 * PHASE 6 — MOBILE CHART COMPONENT
 * 
 * REGRESSION LOCK — mobile charts are read-only
 * REGRESSION LOCK — no persistence
 * 
 * RULE: NO gesture trading, NO editing
 * 
 * Displays a simple line chart of strategy PnL over time.
 * Uses basic React Native components for maximum compatibility.
 * 
 * Note: For production, consider installing react-native-chart-kit or
 * @shopify/react-native-skia for more advanced charting capabilities.
 */

import React, { useMemo } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { normalizeTimeseries, getLatestPnl, getChartBounds } from '../utils/strategyPerformance';

interface StrategyChartProps {
  /**
   * Timeseries data from backend: [[timestamp, pnl_total], ...]
   * May be empty or undefined (handled gracefully)
   */
  series?: [number, number][];
  
  /**
   * Chart height in pixels (default: 120)
   */
  height?: number;
  
  /**
   * Show smooth line (default: true)
   */
  smooth?: boolean;
}

export const StrategyChart: React.FC<StrategyChartProps> = ({
  series,
  height = 120,
  smooth = true,
}) => {
  // PHASE 8: Normalize timeseries data
  const normalizedSeries = useMemo(() => {
    return normalizeTimeseries(series);
  }, [series]);
  
  // PHASE 8: Get latest PnL for color coding
  const latestPnl = useMemo(() => {
    return getLatestPnl(normalizedSeries);
  }, [normalizedSeries]);
  
  // PHASE 8: Calculate chart bounds for scaling
  const bounds = useMemo(() => {
    return getChartBounds(normalizedSeries);
  }, [normalizedSeries]);
  
  // PHASE 8: Determine stroke color based on latest PnL
  const strokeColor = latestPnl >= 0 ? '#10B981' : '#EF4444'; // Green for positive, red for negative
  
  // PHASE 8: Handle empty/missing data gracefully
  if (!series || series.length === 0 || normalizedSeries.length === 0) {
    return (
      <View style={[styles.container, { height }]}>
        <View style={styles.emptyContainer}>
          <Text style={styles.emptyText}>Collecting data…</Text>
        </View>
      </View>
    );
  }
  
  // PHASE 8: Handle invalid bounds
  if (!bounds || bounds.min === bounds.max) {
    return (
      <View style={[styles.container, { height }]}>
        <View style={styles.emptyContainer}>
          <Text style={styles.emptyText}>Insufficient data</Text>
        </View>
      </View>
    );
  }
  
  // Calculate points for simple line visualization
  const chartWidth = 300; // Fixed width for mobile
  const chartHeight = height - 40; // Reserve space for labels
  const range = bounds.max - bounds.min;
  
  // Convert normalized points to chart coordinates
  const points = normalizedSeries.map((point, index) => {
    const x = (index / Math.max(normalizedSeries.length - 1, 1)) * chartWidth;
    const normalizedY = (point.y - bounds.min) / range;
    const y = chartHeight - (normalizedY * chartHeight); // Flip Y axis (0 is at top in React Native)
    return { x, y, value: point.y };
  });
  
  // Create simple line segments using View components
  // This is a simplified visualization - for production, use a proper chart library
  const lineSegments = [];
  for (let i = 0; i < points.length - 1; i++) {
    const p1 = points[i];
    const p2 = points[i + 1];
    
    // Calculate angle and length for line segment
    const dx = p2.x - p1.x;
    const dy = p2.y - p1.y;
    const length = Math.sqrt(dx * dx + dy * dy);
    const angle = Math.atan2(dy, dx) * (180 / Math.PI);
    
    lineSegments.push(
      <View
        key={`segment-${i}`}
        style={[
          styles.lineSegment,
          {
            left: p1.x,
            top: p1.y,
            width: length,
            transform: [{ rotate: `${angle}deg` }],
            backgroundColor: strokeColor,
          },
        ]}
      />
    );
  }
  
  // Draw data points
  const dataPoints = points.map((point, index) => (
    <View
      key={`point-${index}`}
      style={[
        styles.dataPoint,
        {
          left: point.x - 2,
          top: point.y - 2,
          backgroundColor: strokeColor,
        },
      ]}
    />
  ));
  
  return (
    <View style={[styles.container, { height }]}>
      {/* Chart area */}
      <View style={[styles.chartArea, { height: chartHeight, width: chartWidth }]}>
        {/* Grid lines (optional) */}
        <View style={styles.gridLine} />
        <View style={[styles.gridLine, { top: chartHeight / 2 }]} />
        <View style={[styles.gridLine, { top: chartHeight }]} />
        
        {/* Zero line */}
        {bounds.min < 0 && bounds.max > 0 && (
          <View
            style={[
              styles.zeroLine,
              {
                top: chartHeight - ((0 - bounds.min) / range) * chartHeight,
              },
            ]}
          />
        )}
        
        {/* Line segments */}
        {lineSegments}
        
        {/* Data points */}
        {dataPoints}
      </View>
      
      {/* Labels */}
      <View style={styles.labelsContainer}>
        <Text style={styles.label}>
          {bounds.min.toFixed(2)}
        </Text>
        <Text style={[styles.label, styles.labelCenter]}>
          {latestPnl >= 0 ? '+' : ''}{latestPnl.toFixed(2)}
        </Text>
        <Text style={[styles.label, styles.labelRight]}>
          {bounds.max.toFixed(2)}
        </Text>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    width: '100%',
    padding: 8,
    backgroundColor: '#F9FAFB',
    borderRadius: 8,
  },
  emptyContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  emptyText: {
    fontSize: 12,
    color: '#9CA3AF',
    fontStyle: 'italic',
  },
  chartArea: {
    position: 'relative',
    borderLeftWidth: 1,
    borderBottomWidth: 1,
    borderColor: '#D1D5DB',
    marginBottom: 4,
  },
  gridLine: {
    position: 'absolute',
    left: 0,
    right: 0,
    height: 1,
    backgroundColor: '#E5E7EB',
    opacity: 0.5,
  },
  zeroLine: {
    position: 'absolute',
    left: 0,
    right: 0,
    height: 1,
    backgroundColor: '#6B7280',
    opacity: 0.3,
  },
  lineSegment: {
    position: 'absolute',
    height: 2,
    transformOrigin: 'left center',
  },
  dataPoint: {
    position: 'absolute',
    width: 4,
    height: 4,
    borderRadius: 2,
  },
  labelsContainer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingHorizontal: 4,
  },
  label: {
    fontSize: 10,
    color: '#6B7280',
  },
  labelCenter: {
    textAlign: 'center',
    flex: 1,
    fontWeight: '600',
  },
  labelRight: {
    textAlign: 'right',
  },
});
