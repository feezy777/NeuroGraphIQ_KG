import { createStore } from "./create-store.js";

const store = createStore({
  nodes: [],
  edges: [],
  layerFilter: "all",
  review: {
    entities: [],
    relations: [],
    circuits: [],
  },
});

function updateStatus(items, id, status) {
  return (items || []).map((item) => (item.id === id ? { ...item, status } : item));
}

export const graphStore = {
  ...store,
  setGraphData({ nodes = [], edges = [] }) {
    store.setState({ nodes, edges });
  },
  setReviewData(review) {
    store.setState({
      review: {
        entities: review?.entities || [],
        relations: review?.relations || [],
        circuits: review?.circuits || [],
      },
    });
  },
  setFilter(layerFilter) {
    store.setState({ layerFilter: layerFilter || "all" });
  },
  updateReviewStatus(type, id, status) {
    store.setState((state) => {
      if (type === "entity") {
        return {
          review: {
            ...state.review,
            entities: updateStatus(state.review.entities, id, status),
          },
        };
      }
      if (type === "relation") {
        return {
          review: {
            ...state.review,
            relations: updateStatus(state.review.relations, id, status),
          },
        };
      }
      return {
        review: {
          ...state.review,
          circuits: updateStatus(state.review.circuits, id, status),
        },
      };
    });
  },
};
