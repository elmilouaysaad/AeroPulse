#!/usr/bin/env bash
# Broker-failure drill: verify that stopping one Kafka broker out of three
# does not interrupt the pipeline, and that the ISR recovers on restart.
#
# Run from repo root: ./scripts/kafka-drill.sh
set -euo pipefail

KCLI="/opt/kafka/bin/kafka-topics.sh"

inspect_isr() {
    docker exec aeropulse-kafka-1 "$KCLI" \
        --bootstrap-server localhost:9092 \
        --describe --topic aircraft_state \
        | grep -E 'Partition:' | head -6
}

echo "=== Baseline: all three replicas in ISR ==="
inspect_isr

echo ""
echo "=== Stopping kafka-2 (simulating broker failure) ==="
docker stop aeropulse-kafka-2 >/dev/null
echo "Waiting 20s for controller to detect failure..."
sleep 20

echo ""
echo "=== ISR should now be 2 per partition (broker-2 excluded) ==="
inspect_isr

echo ""
echo "=== Verifying the producer still works ==="
docker exec aeropulse-kafka-1 /opt/kafka/bin/kafka-console-producer.sh \
    --bootstrap-server localhost:9092 \
    --topic aircraft_state <<< \
    'drill-test:{"hex":"drill-test","flight":"TEST1","lat":40.6413,"lon":-73.7781,"alt_baro_ft":28000.0,"gs_kts":420.0,"track_deg":90.0,"squawk":"1200","seen_sec":1.0,"seen_pos_sec":1.0,"on_ground":false}' \
    && echo "Producer write OK with one broker down"

echo ""
echo "=== Restarting kafka-2 ==="
docker start aeropulse-kafka-2 >/dev/null
echo "Waiting 30s for ISR to re-expand..."
sleep 30

echo ""
echo "=== ISR should be back to 3 per partition ==="
inspect_isr

echo ""
echo "Drill complete."