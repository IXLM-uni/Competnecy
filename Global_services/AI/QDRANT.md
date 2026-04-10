Collections
A collection is a named set of points (vectors with a payload) among which you can search. The vector of each point within the same collection must have the same dimensionality and be compared by a single metric. Named vectors can be used to have multiple vectors in a single point, each of which can have their own dimensionality and metric requirements.

Distance metrics are used to measure similarities among vectors. The choice of metric depends on the way vectors obtaining and, in particular, on the method of neural network encoder training.

Qdrant supports these most popular types of metrics:

Dot product: Dot - [wiki]
Cosine similarity: Cosine - [wiki]
Euclidean distance: Euclid - [wiki]
Manhattan distance: Manhattan - [wiki]
For search efficiency, Cosine similarity is implemented as dot-product over normalized vectors. Vectors are automatically normalized during upload
In addition to metrics and vector size, each collection uses its own set of parameters that controls collection optimization, index construction, and vacuum. These settings can be changed at any time by a corresponding request.

Setting up multitenancy
How many collections should you create? In most cases, you should only use a single collection with payload-based partitioning. This approach is called multitenancy. It is efficient for most of users, but it requires additional configuration. Learn how to set it up

When should you create multiple collections? When you have a limited number of users and you need isolation. This approach is flexible, but it may be more costly, since creating numerous collections may result in resource overhead. Also, you need to ensure that they do not affect each other in any way, including performance-wise.

Create a collection
http
bash
python
typescript
rust
java
csharp
go
curl -X PUT http://localhost:6333/collections/{collection_name} \
  -H 'Content-Type: application/json' \
  --data-raw '{
    "vectors": {
      "size": 100,
      "distance": "Cosine"
    }
  }'

In addition to the required options, you can also specify custom values for the following collection options:

hnsw_config - see indexing for details.
wal_config - Write-Ahead-Log related configuration. See more details about WAL
optimizers_config - see optimizer for details.
shard_number - which defines how many shards the collection should have. See distributed deployment section for details.
on_disk_payload - defines where to store payload data. If true - payload will be stored on disk only. Might be useful for limiting the RAM usage in case of large payload.
quantization_config - see quantization for details.
strict_mode_config - see strict mode for details.
Default parameters for the optional collection parameters are defined in configuration file.

See schema definitions and a configuration file for more information about collection and vector parameters.

Available as of v1.2.0

Vectors all live in RAM for very quick access. The on_disk parameter can be set in the vector configuration. If true, all vectors will live on disk. This will enable the use of memmaps, which is suitable for ingesting a large amount of data.

Collection with multiple vectors
Available as of v0.10.0

It is possible to have multiple vectors per record. This feature allows for multiple vector storages per collection. To distinguish vectors in one record, they should have a unique name defined when creating the collection. Each named vector in this mode has its distance and size:

http
bash
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.create_collection(
    collection_name="{collection_name}",
    vectors_config={
        "image": models.VectorParams(size=4, distance=models.Distance.DOT),
        "text": models.VectorParams(size=8, distance=models.Distance.COSINE),
    },
)

For rare use cases, it is possible to create a collection without any vector storage.

Available as of v1.1.1

For each named vector you can optionally specify hnsw_config or quantization_config to deviate from the collection configuration. This can be useful to fine-tune search performance on a vector level.

Available as of v1.2.0

Vectors all live in RAM for very quick access. On a per-vector basis you can set on_disk to true to store all vectors on disk at all times. This will enable the use of memmaps, which is suitable for ingesting a large amount of data.

Vector datatypes
Available as of v1.9.0

Some embedding providers may provide embeddings in a pre-quantized format. One of the most notable examples is the Cohere int8 & binary embeddings. Qdrant has direct support for uint8 embeddings, which you can also use in combination with binary quantization.

To create a collection with uint8 embeddings, you can use the following configuration:

http
bash
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.create_collection(
    collection_name="{collection_name}",
    vectors_config=models.VectorParams(
        size=1024,
        distance=models.Distance.COSINE,
        datatype=models.Datatype.UINT8,
    ),
)

Vectors with uint8 datatype are stored in a more compact format, which can save memory and improve search speed at the cost of some precision. If you choose to use the uint8 datatype, elements of the vector will be stored as unsigned 8-bit integers, which can take values from 0 to 255.

Collection with sparse vectors
Available as of v1.7.0

Qdrant supports sparse vectors as a first-class citizen.

Sparse vectors are useful for text search, where each word is represented as a separate dimension.

Collections can contain sparse vectors as additional named vectors along side regular dense vectors in a single point.

Unlike dense vectors, sparse vectors must be named. And additionally, sparse vectors and dense vectors must have different names within a collection.

http
bash
python
typescript
rust
java
csharp
go
PUT /collections/{collection_name}
{
    "sparse_vectors": {
        "text": { }
    }
}

Outside of a unique name, there are no required configuration parameters for sparse vectors.

The distance function for sparse vectors is always Dot and does not need to be specified.

However, there are optional parameters to tune the underlying sparse vector index.

Create collection from another collection
To create a collection from another collection, use the Migration Tool. You can use it to either copy a collection within the same Qdrant instance or to copy a collection to another instance.

For example, to copy a collection from a local instance to a Qdrant Cloud instance, run the following command:

docker run --net=host --rm -it registry.cloud.qdrant.io/library/qdrant-migration qdrant \
    --source.url 'http://localhost:6334' \
    --source.collection 'source-collection' \
    --target.url 'https://example.cloud-region.cloud-provider.cloud.qdrant.io:6334' \
    --target.api-key 'qdrant-key' \
    --target.collection 'target-collection' \
    --migration.batch-size 64

Check collection existence
Available as of v1.8.0

http
bash
python
typescript
rust
java
csharp
go
client.collection_exists(collection_name="{collection_name}")

Delete collection
http
bash
python
typescript
rust
java
csharp
go
client.delete_collection(collection_name="{collection_name}")

Update collection parameters
Dynamic parameter updates may be helpful, for example, for more efficient initial loading of vectors. For example, you can disable indexing during the upload process, and enable it immediately after the upload is finished. As a result, you will not waste extra computation resources on rebuilding the index.

The following command enables indexing for segments that have more than 10000 kB of vectors stored:

http
bash
python
typescript
rust
java
csharp
go
client.update_collection(
    collection_name="{collection_name}",
    optimizers_config=models.OptimizersConfigDiff(indexing_threshold=10000),
)

The following parameters can be updated:

optimizers_config - see optimizer for details.
hnsw_config - see indexing for details.
quantization_config - see quantization for details.
vectors_config - vector-specific configuration, including individual hnsw_config, quantization_config and on_disk settings.
params - other collection parameters, including write_consistency_factor and on_disk_payload.
strict_mode_config - see strict mode for details.
Full API specification is available in schema definitions.

Calls to this endpoint may be blocking as it waits for existing optimizers to finish. We recommended against using this in a production database as it may introduce huge overhead due to the rebuilding of the index.

Update vector parameters
Available as of v1.4.0

To update vector parameters using the collection update API, you must always specify a vector name. If your collection does not have named vectors, use an empty ("") name.
Qdrant 1.4 adds support for updating more collection parameters at runtime. HNSW index, quantization and disk configurations can now be changed without recreating a collection. Segments (with index and quantized data) will automatically be rebuilt in the background to match updated parameters.

To put vector data on disk for a collection that does not have named vectors, use "" as name:

http
bash
PATCH /collections/{collection_name}
{
    "vectors": {
        "": {
            "on_disk": true
        }
    }
}

To put vector data on disk for a collection that does have named vectors:

Note: To create a vector name, follow the procedure from our Points.

http
bash
PATCH /collections/{collection_name}
{
    "vectors": {
        "my_vector": {
            "on_disk": true
        }
    }
}

In the following example the HNSW index and quantization parameters are updated, both for the whole collection, and for my_vector specifically:

http
bash
python
typescript
rust
java
csharp
go
client.update_collection(
    collection_name="{collection_name}",
    vectors_config={
        "my_vector": models.VectorParamsDiff(
            hnsw_config=models.HnswConfigDiff(
                m=32,
                ef_construct=123,
            ),
            quantization_config=models.ProductQuantization(
                product=models.ProductQuantizationConfig(
                    compression=models.CompressionRatio.X32,
                    always_ram=True,
                ),
            ),
            on_disk=True,
        ),
    },
    hnsw_config=models.HnswConfigDiff(
        ef_construct=123,
    ),
    quantization_config=models.ScalarQuantization(
        scalar=models.ScalarQuantizationConfig(
            type=models.ScalarType.INT8,
            quantile=0.8,
            always_ram=False,
        ),
    ),
)

Collection info
Qdrant allows determining the configuration parameters of an existing collection to better understand how the points are distributed and indexed.

http
bash
python
typescript
rust
java
csharp
go
client.get_collection(collection_name="{collection_name}")

Expected result
If you insert the vectors into the collection, the status field may become yellow whilst it is optimizing. It will become green once all the points are successfully processed.

The following color statuses are possible:

🟢 green: collection is ready
🟡 yellow: collection is optimizing
⚫ grey: collection is pending optimization (help)
🔴 red: an error occurred which the engine could not recover from
Grey collection status
Available as of v1.9.0

A collection may have the grey ⚫ status or show “optimizations pending, awaiting update operation” as optimization status. This state is normally caused by restarting a Qdrant instance while optimizations were ongoing.

It means the collection has optimizations pending, but they are paused. You must send any update operation to trigger and start the optimizations again.

For example:

http
bash
python
typescript
rust
java
csharp
go
client.update_collection(
    collection_name="{collection_name}",
    optimizer_config=models.OptimizersConfigDiff(),
)

Alternatively you may use the Trigger Optimizers button in the Qdrant Web UI. It is shown next to the grey collection status on the collection info page.

Approximate point and vector counts
You may be interested in the count attributes:

points_count - total number of objects (vectors and their payloads) stored in the collection
indexed_vectors_count - total number of vectors stored in the HNSW or sparse index. Qdrant does not store all the vectors in the index, but only if an index segment might be created for a given configuration.
The above counts are not exact, but should be considered approximate. Depending on how you use Qdrant these may give very different numbers than what you may expect. It’s therefore important not to rely on them.

More specifically, these numbers represent the count of points and vectors in Qdrant’s internal storage. Internally, Qdrant may temporarily duplicate points as part of automatic optimizations. It may keep changed or deleted points for a bit. And it may delay indexing of new points. All of that is for optimization reasons.

Updates you do are therefore not directly reflected in these numbers. If you see a wildly different count of points, it will likely resolve itself once a new round of automatic optimizations is completed.

To clarify: these numbers don’t represent the exact amount of points or vectors you have inserted, nor does it represent the exact number of distinguishable points or vectors you can query. If you want to know exact counts, refer to the count API.

Note: these numbers may be removed in a future version of Qdrant.

Indexing vectors in HNSW
In some cases, you might be surprised the value of indexed_vectors_count is lower than you expected. This is an intended behaviour and depends on the optimizer configuration. A new index segment is built if the size of non-indexed vectors is higher than the value of indexing_threshold(in kB). If your collection is very small or the dimensionality of the vectors is low, there might be no HNSW segment created and indexed_vectors_count might be equal to 0.

It is possible to reduce the indexing_threshold for an existing collection by updating collection parameters.

Collection metadata
Available as of v1.16.0

For convenience and better data organization, Qdrant allows attaching custom metadata to collections in the form of key-value pairs. Adding metadata is treated as a part of collection configuration and synchronized across all nodes in a cluster with consensus protocol.

Collection metadata can be specified during collection creation:

http
bash
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.create_collection(
    collection_name="{collection_name}",
    metadata={
        "my-metadata-field": "value-1",
        "another-field": 123
    },
)

as well as updated later:

http
bash
python
typescript
rust
java
csharp
go
client.update_collection(
    collection_name="{collection_name}",
    metadata={
        "my-metadata-field": {
            "key-a": "value-a",
            "key-b": 42
        }
    },
)

Note, that update operation only modifies the specified metadata fields, leaving other fields unchanged.

When specified, metadata is returned as part of collection info:

{
    "result": {
        "config": {
            "metadata": {
                "my-metadata-field": {
                    "key-a": "value-a",
                    "key-b": 42
                },
                "another-field": 123
            }
        }
    }
}

Collection aliases
In a production environment, it is sometimes necessary to switch different versions of vectors seamlessly. For example, when upgrading to a new version of the neural network.

There is no way to stop the service and rebuild the collection with new vectors in these situations. Aliases are additional names for existing collections. All queries to the collection can also be done identically, using an alias instead of the collection name.

Thus, it is possible to build a second collection in the background and then switch alias from the old to the new collection. Since all changes of aliases happen atomically, no concurrent requests will be affected during the switch.

Create alias
http
bash
python
typescript
rust
java
csharp
go
client.update_collection_aliases(
    change_aliases_operations=[
        models.CreateAliasOperation(
            create_alias=models.CreateAlias(
                collection_name="example_collection", alias_name="production_collection"
            )
        )
    ]
)

Remove alias
http
bash
python
typescript
rust
java
csharp
go
client.update_collection_aliases(
    change_aliases_operations=[
        models.DeleteAliasOperation(
            delete_alias=models.DeleteAlias(alias_name="production_collection")
        ),
    ]
)

Switch collection
Multiple alias actions are performed atomically. For example, you can switch underlying collection with the following command:

http
bash
python
typescript
rust
java
csharp
go
client.update_collection_aliases(
    change_aliases_operations=[
        models.DeleteAliasOperation(
            delete_alias=models.DeleteAlias(alias_name="production_collection")
        ),
        models.CreateAliasOperation(
            create_alias=models.CreateAlias(
                collection_name="example_collection", alias_name="production_collection"
            )
        ),
    ]
)

List collection aliases
http
bash
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient

client = QdrantClient(url="http://localhost:6333")

client.get_collection_aliases(collection_name="{collection_name}")

List all aliases
http
bash
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient

client = QdrantClient(url="http://localhost:6333")

client.get_aliases()

List all collections
http
bash
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient

client = QdrantClient(url="http://localhost:6333")

client.get_collections()

Was this page useful?
Thumb up iconYes
Thumb down iconNo





Points
The points are the central entity that Qdrant operates with. A point is a record consisting of a vector and an optional payload.

It looks like this:

// This is a simple point
{
    "id": 129,
    "vector": [0.1, 0.2, 0.3, 0.4],
    "payload": {"color": "red"},
}

You can search among the points grouped in one collection based on vector similarity. This procedure is described in more detail in the search and filtering sections.

This section explains how to create and manage vectors.

Any point modification operation is asynchronous and takes place in 2 steps. At the first stage, the operation is written to the Write-ahead-log.

After this moment, the service will not lose the data, even if the machine loses power supply.

Point IDs
Qdrant supports using both 64-bit unsigned integers and UUID as identifiers for points.

Examples of UUID string representations:

simple: 936DA01F9ABD4d9d80C702AF85C822A8
hyphenated: 550e8400-e29b-41d4-a716-446655440000
urn: urn:uuid:F9168C5E-CEB2-4faa-B6BF-329BF39FA1E4
That means that in every request UUID string could be used instead of numerical id. Example:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.upsert(
    collection_name="{collection_name}",
    points=[
        models.PointStruct(
            id="5c56c793-69f3-4fbf-87e6-c4bf54c28c26",
            payload={
                "color": "red",
            },
            vector=[0.9, 0.1, 0.1],
        ),
    ],
)

and

http
python
typescript
rust
java
csharp
go
client.upsert(
    collection_name="{collection_name}",
    points=[
        models.PointStruct(
            id=1,
            payload={
                "color": "red",
            },
            vector=[0.9, 0.1, 0.1],
        ),
    ],
)

are both possible.

Vectors
Each point in qdrant may have one or more vectors. Vectors are the central component of the Qdrant architecture, qdrant relies on different types of vectors to provide different types of data exploration and search.

Here is a list of supported vector types:

Dense Vectors	A regular vectors, generated by majority of the embedding models.
Sparse Vectors	Vectors with no fixed length, but only a few non-zero elements.
Useful for exact token match and collaborative filtering recommendations.
MultiVectors	Matrices of numbers with fixed length but variable height.
Usually obtained from late interaction models like ColBERT.
It is possible to attach more than one type of vector to a single point. In Qdrant we call these Named Vectors.

Read more about vector types, how they are stored and optimized in the vectors section.

Upload points
To optimize performance, Qdrant supports batch loading of points. I.e., you can load several points into the service in one API call. Batching allows you to minimize the overhead of creating a network connection.

The Qdrant API supports two ways of creating batches - record-oriented and column-oriented. Internally, these options do not differ and are made only for the convenience of interaction.

Create points with batch:

http
python
typescript
client.upsert(
    collection_name="{collection_name}",
    points=models.Batch(
        ids=[1, 2, 3],
        payloads=[
            {"color": "red"},
            {"color": "green"},
            {"color": "blue"},
        ],
        vectors=[
            [0.9, 0.1, 0.1],
            [0.1, 0.9, 0.1],
            [0.1, 0.1, 0.9],
        ],
    ),
)

or record-oriented equivalent:

http
python
typescript
rust
java
csharp
go
client.upsert(
    collection_name="{collection_name}",
    points=[
        models.PointStruct(
            id=1,
            payload={
                "color": "red",
            },
            vector=[0.9, 0.1, 0.1],
        ),
        models.PointStruct(
            id=2,
            payload={
                "color": "green",
            },
            vector=[0.1, 0.9, 0.1],
        ),
        models.PointStruct(
            id=3,
            payload={
                "color": "blue",
            },
            vector=[0.1, 0.1, 0.9],
        ),
    ],
)

Python client optimizations
The Python client has additional features for loading points, which include:

Parallelization
A retry mechanism
Lazy batching support
For example, you can read your data directly from hard drives, to avoid storing all data in RAM. You can use these features with the upload_collection and upload_points methods. Similar to the basic upsert API, these methods support both record-oriented and column-oriented formats.

upload_points is available as of v1.7.1. It has replaced upload_records which is now deprecated.
Column-oriented format:

client.upload_collection(
    collection_name="{collection_name}",
    ids=[1, 2],
    payload=[
        {"color": "red"},
        {"color": "green"},
    ],
    vectors=[
        [0.9, 0.1, 0.1],
        [0.1, 0.9, 0.1],
    ],
    parallel=4,
    max_retries=3,
)

If ids are not provided, Qdrant Client will generate them automatically as random UUIDs.
Record-oriented format:

client.upload_points(
    collection_name="{collection_name}",
    points=[
        models.PointStruct(
            id=1,
            payload={
                "color": "red",
            },
            vector=[0.9, 0.1, 0.1],
        ),
        models.PointStruct(
            id=2,
            payload={
                "color": "green",
            },
            vector=[0.1, 0.9, 0.1],
        ),
    ],
    parallel=4,
    max_retries=3,
)

Idempotence
All APIs in Qdrant, including point loading, are idempotent. It means that executing the same method several times in a row is equivalent to a single execution.

In this case, it means that points with the same id will be overwritten when re-uploaded.

Idempotence property is useful if you use, for example, a message queue that doesn’t provide an exactly-once guarantee. Even with such a system, Qdrant ensures data consistency.

Named vectors
Available as of v0.10.0

If the collection was created with multiple vectors, each vector data can be provided using the vector’s name:

http
python
typescript
rust
java
csharp
go
client.upsert(
    collection_name="{collection_name}",
    points=[
        models.PointStruct(
            id=1,
            vector={
                "image": [0.9, 0.1, 0.1, 0.2],
                "text": [0.4, 0.7, 0.1, 0.8, 0.1, 0.1, 0.9, 0.2],
            },
        ),
        models.PointStruct(
            id=2,
            vector={
                "image": [0.2, 0.1, 0.3, 0.9],
                "text": [0.5, 0.2, 0.7, 0.4, 0.7, 0.2, 0.3, 0.9],
            },
        ),
    ],
)

Available as of v1.2.0

Named vectors are optional. When uploading points, some vectors may be omitted. For example, you can upload one point with only the image vector and a second one with only the text vector.

When uploading a point with an existing ID, the existing point is deleted first, then it is inserted with just the specified vectors. In other words, the entire point is replaced, and any unspecified vectors are set to null. To keep existing vectors unchanged and only update specified vectors, see update vectors.

Sparse vectors
Available as of v1.7.0

Points can contain dense and sparse vectors.

A sparse vector is an array in which most of the elements have a value of zero.

It is possible to take advantage of this property to have an optimized representation, for this reason they have a different shape than dense vectors.

They are represented as a list of (index, value) pairs, where index is an integer and value is a floating point number. The index is the position of the non-zero value in the vector. The values is the value of the non-zero element.

For example, the following vector:

[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 2.0, 0.0, 0.0]
can be represented as a sparse vector:

[(6, 1.0), (7, 2.0)]
Qdrant uses the following JSON representation throughout its APIs.

{
  "indices": [6, 7],
  "values": [1.0, 2.0]
}

The indices and values arrays must have the same length. And the indices must be unique.

If the indices are not sorted, Qdrant will sort them internally so you may not rely on the order of the elements.

Sparse vectors must be named and can be uploaded in the same way as dense vectors.

http
python
typescript
rust
java
csharp
go
client.upsert(
    collection_name="{collection_name}",
    points=[
        models.PointStruct(
            id=1,
            vector={
                "text": models.SparseVector(
                    indices=[6, 7],
                    values=[1.0, 2.0],
                )
            },
        ),
        models.PointStruct(
            id=2,
            vector={
                "text": models.SparseVector(
                    indices=[1, 2, 3, 4, 5],
                    values=[0.1, 0.2, 0.3, 0.4, 0.5],
                )
            },
        ),
    ],
)

Inference
Instead of providing vectors explicitly, Qdrant can also generate vectors using a process called inference. Inference is the process of creating vector embeddings from text, images, or other data types using a machine learning model.

You can use inference in the API wherever you can use regular vectors. For example, while upserting points, you can provide the text or image and the embedding model:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(
    url="https://xyz-example.qdrant.io:6333", 
    api_key="<your-api-key>", 
    cloud_inference=True
)

client.upsert(
    collection_name="{collection_name}",
    points=[
        models.PointStruct(
            id=1,
            vector={
                "my-bm25-vector": models.Document(
                    text="Recipe for baking chocolate chip cookies",
                    model="Qdrant/bm25",
                )
            },
        )
    ],
)

Qdrant uses the model to generate the embeddings and store the point with the resulting vector.

Modify points
To change a point, you can modify its vectors or its payload. There are several ways to do this.

Update vectors
Available as of v1.2.0

This method updates the specified vectors on the given points. Unspecified vectors are kept unchanged. All given points must exist.

REST API (Schema):

http
python
typescript
rust
java
csharp
go
client.update_vectors(
    collection_name="{collection_name}",
    points=[
        models.PointVectors(
            id=1,
            vector={
                "image": [0.1, 0.2, 0.3, 0.4],
            },
        ),
        models.PointVectors(
            id=2,
            vector={
                "text": [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2],
            },
        ),
    ],
)

To update points and replace all of its vectors, see uploading points.

Delete vectors
Available as of v1.2.0

This method deletes just the specified vectors from the given points. Other vectors are kept unchanged. Points are never deleted.

REST API (Schema):

http
python
typescript
rust
java
csharp
go
client.delete_vectors(
    collection_name="{collection_name}",
    points=[0, 3, 100],
    vectors=["text", "image"],
)

To delete entire points, see deleting points.

Update payload
Learn how to modify the payload of a point in the Payload section.

Delete points
REST API (Schema):

http
python
typescript
rust
java
csharp
go
client.delete(
    collection_name="{collection_name}",
    points_selector=models.PointIdsList(
        points=[0, 3, 100],
    ),
)

Alternative way to specify which points to remove is to use filter.

http
python
typescript
rust
java
csharp
go
client.delete(
    collection_name="{collection_name}",
    points_selector=models.FilterSelector(
        filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="color",
                    match=models.MatchValue(value="red"),
                ),
            ],
        )
    ),
)

This example removes all points with { "color": "red" } from the collection.

Conditional updates
Available as of v1.16.0

All update operations (including point insertion, vector updates, payload updates, and deletions) support configurable pre-conditions based on filters.

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.upsert(
    collection_name="{collection_name}",
    points=[
        models.PointStruct(
            id=1,
            vector=[0.05, 0.61, 0.76, 0.74],
            payload={
                "city": "Berlin",
                "price": 1.99,
                "version": 3,
            },
        ),
    ],
    update_filter=models.Filter(
        must=[
            models.FieldCondition(
                key="version",
                match=models.MatchValue(value=2),
            ),
        ],
    ),
)

While conditional payload modification and deletion covers the use-case of mass data modification, conditional point insertion and vector updates are particularly useful for implementing optimistic concurrency control in distributed systems.

A common scenario for such mechanism is when multiple clients try to update the same point independently. Consider the following sequence of events:

Client A reads point P.
Client B reads point P.
Client A modifies point P and writes it back to Qdrant.
Client B modifies point P (based on the stale data) and writes it back to Qdrant, unintentionally overwriting changes made by Client A.
To prevent such situations, Client B can use conditional updates. For this, we would need to introduce an additional field in the payload, e.g. version, which would be incremented on each update.

When Client A writes back the modified point P, it would set the condition that the version field must be equal to the value it read initially. If Client B tries to write back its changes later, the condition would fail (as the version has been incremented by Client A), and Qdrant would reject the update, preventing accidental overwrites.

Instead of version, applications can use timestamps (assuming synchronized clocks) or any other monotonically increasing value that fits their data model.

This mechanism is especially useful in the scenarios of embedding model migration, where we need to resolve conflicts between regular application updates and background re-embedding tasks.

Embedding model migration in blue-green deployment
Embedding model migration in blue-green deployment

Retrieve points
There is a method for retrieving points by their ids.

REST API (Schema):

http
python
typescript
rust
java
csharp
go
client.retrieve(
    collection_name="{collection_name}",
    ids=[0, 3, 100],
)

This method has additional parameters with_vectors and with_payload. Using these parameters, you can select parts of the point you want as a result. Excluding helps you not to waste traffic transmitting useless data.

The single point can also be retrieved via the API:

REST API (Schema):

GET /collections/{collection_name}/points/{point_id}

Scroll points
Sometimes it might be necessary to get all stored points without knowing ids, or iterate over points that correspond to a filter.

REST API (Schema):

http
python
typescript
rust
java
csharp
go
client.scroll(
    collection_name="{collection_name}",
    scroll_filter=models.Filter(
        must=[
            models.FieldCondition(key="color", match=models.MatchValue(value="red")),
        ]
    ),
    limit=1,
    with_payload=True,
    with_vectors=False,
)

Returns all point with color = red.

{
  "result": {
    "next_page_offset": 1,
    "points": [
      {
        "id": 0,
        "payload": {
          "color": "red"
        }
      }
    ]
  },
  "status": "ok",
  "time": 0.0001
}

The Scroll API will return all points that match the filter in a page-by-page manner.

All resulting points are sorted by ID. To query the next page it is necessary to specify the largest seen ID in the offset field. For convenience, this ID is also returned in the field next_page_offset. If the value of the next_page_offset field is null - the last page is reached.

Order points by payload key
Available as of v1.8.0

When using the scroll API, you can sort the results by payload key. For example, you can retrieve points in chronological order if your payloads have a "timestamp" field, as is shown from the example below:

Without an appropriate index, payload-based ordering would create too much load on the system for each request. Qdrant therefore requires a payload index which supports Range filtering conditions on the field used for order_by
http
python
typescript
rust
java
csharp
go
client.scroll(
    collection_name="{collection_name}",
    limit=15,
    order_by="timestamp", # <-- this!
)

You need to use the order_by key parameter to specify the payload key. Then you can add other fields to control the ordering, such as direction and start_from:

http
python
typescript
rust
java
csharp
go
"order_by": {
    "key": "timestamp",
    "direction": "desc" // default is "asc"
    "start_from": 123, // start from this value
}

When you use the order_by parameter, pagination is disabled.
When sorting is based on a non-unique value, it is not possible to rely on an ID offset. Thus, next_page_offset is not returned within the response. However, you can still do pagination by combining "order_by": { "start_from": ... } with a { "must_not": [{ "has_id": [...] }] } filter.

Counting points
Available as of v0.8.4

Sometimes it can be useful to know how many points fit the filter conditions without doing a real search.

Among others, for example, we can highlight the following scenarios:

Evaluation of results size for faceted search
Determining the number of pages for pagination
Debugging the query execution speed
REST API (Schema):

http
python
typescript
rust
java
csharp
go
client.count(
    collection_name="{collection_name}",
    count_filter=models.Filter(
        must=[
            models.FieldCondition(key="color", match=models.MatchValue(value="red")),
        ]
    ),
    exact=True,
)

Returns number of counts matching given filtering conditions:

{
  "count": 3811
}

Batch update
Available as of v1.5.0

You can batch multiple point update operations. This includes inserting, updating and deleting points, vectors and payload.

A batch update request consists of a list of operations. These are executed in order. These operations can be batched:

Upsert points: upsert or UpsertOperation
Delete points: delete_points or DeleteOperation
Update vectors: update_vectors or UpdateVectorsOperation
Delete vectors: delete_vectors or DeleteVectorsOperation
Set payload: set_payload or SetPayloadOperation
Overwrite payload: overwrite_payload or OverwritePayload
Delete payload: delete_payload or DeletePayloadOperation
Clear payload: clear_payload or ClearPayloadOperation
The following example snippet makes use of all operations.

REST API (Schema):

http
python
typescript
rust
java
client.batch_update_points(
    collection_name="{collection_name}",
    update_operations=[
        models.UpsertOperation(
            upsert=models.PointsList(
                points=[
                    models.PointStruct(
                        id=1,
                        vector=[1.0, 2.0, 3.0, 4.0],
                        payload={},
                    ),
                ]
            )
        ),
        models.UpdateVectorsOperation(
            update_vectors=models.UpdateVectors(
                points=[
                    models.PointVectors(
                        id=1,
                        vector=[1.0, 2.0, 3.0, 4.0],
                    )
                ]
            )
        ),
        models.DeleteVectorsOperation(
            delete_vectors=models.DeleteVectors(points=[1], vector=[""])
        ),
        models.OverwritePayloadOperation(
            overwrite_payload=models.SetPayload(
                payload={"test_payload": 1},
                points=[1],
            )
        ),
        models.SetPayloadOperation(
            set_payload=models.SetPayload(
                payload={
                    "test_payload_2": 2,
                    "test_payload_3": 3,
                },
                points=[1],
            )
        ),
        models.DeletePayloadOperation(
            delete_payload=models.DeletePayload(keys=["test_payload_2"], points=[1])
        ),
        models.ClearPayloadOperation(clear_payload=models.PointIdsList(points=[1])),
        models.DeleteOperation(delete=models.PointIdsList(points=[1])),
    ],
)

To batch many points with a single operation type, please use batching functionality in that operation directly.

Awaiting result
If the API is called with the &wait=false parameter, or if it is not explicitly specified, the client will receive an acknowledgment of receiving data:

{
  "result": {
    "operation_id": 123,
    "status": "acknowledged"
  },
  "status": "ok",
  "time": 0.000206061
}

This response does not mean that the data is available for retrieval yet. This uses a form of eventual consistency. It may take a short amount of time before it is actually processed as updating the collection happens in the background. In fact, it is possible that such request eventually fails. If inserting a lot of vectors, we also recommend using asynchronous requests to take advantage of pipelining.

If the logic of your application requires a guarantee that the vector will be available for searching immediately after the API responds, then use the flag ?wait=true. In this case, the API will return the result only after the operation is finished:

{
  "result": {
    "operation_id": 0,
    "status": "completed"
  },
  "status": "ok",
  "time": 0.000206061
}

Vectors
Vectors (or embeddings) are the core concept of the Qdrant Vector Search engine. Vectors define the similarity between objects in the vector space.

If a pair of vectors are similar in vector space, it means that the objects they represent are similar in some way.

For example, if you have a collection of images, you can represent each image as a vector. If two images are similar, their vectors will be close to each other in the vector space.

In order to obtain a vector representation of an object, you need to apply a vectorization algorithm to the object. Usually, this algorithm is a neural network that converts the object into a fixed-size vector.

The neural network is usually trained on a pairs or triplets of similar and dissimilar objects, so it learns to recognize a specific type of similarity.

By using this property of vectors, you can explore your data in a number of ways; e.g. by searching for similar objects, clustering objects, and more.

Vector Types
Modern neural networks can output vectors in different shapes and sizes, and Qdrant supports most of them. Let’s take a look at the most common types of vectors supported by Qdrant.

Dense Vectors
This is the most common type of vector. It is a simple list of numbers, it has a fixed length and each element of the list is a floating-point number.

It looks like this:


// A piece of a real-world dense vector
[
    -0.013052909,
    0.020387933,
    -0.007869,
    -0.11111383,
    -0.030188112,
    -0.0053388323,
    0.0010654867,
    0.072027855,
    -0.04167721,
    0.014839341,
    -0.032948174,
    -0.062975034,
    -0.024837125,
    ....
]

The majority of neural networks create dense vectors, so you can use them with Qdrant without any additional processing. Although compatible with most embedding models out there, Qdrant has been tested with the following verified embedding providers.

Sparse Vectors
Sparse vectors are a special type of vectors. Mathematically, they are the same as dense vectors, but they contain many zeros so they are stored in a special format.

Sparse vectors in Qdrant don’t have a fixed length, as it is dynamically allocated during vector insertion. The amount of non-zero values in sparse vectors is currently limited to u32 datatype range (4294967295).

In order to define a sparse vector, you need to provide a list of non-zero elements and their indexes.

// A sparse vector with 4 non-zero elements
{
    "indexes": [1, 3, 5, 7],
    "values": [0.1, 0.2, 0.3, 0.4]
}

Sparse vectors in Qdrant are kept in special storage and indexed in a separate index, so their configuration is different from dense vectors.

To create a collection with sparse vectors:

http
bash
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.create_collection(
    collection_name="{collection_name}",
    vectors_config={},
    sparse_vectors_config={
        "text": models.SparseVectorParams(),
    },
)

Insert a point with a sparse vector into the created collection:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.upsert(
    collection_name="{collection_name}",
    points=[
        models.PointStruct(
            id=1,
            payload={},  # Add any additional payload if necessary
            vector={
                "text": models.SparseVector(
                    indices=[1, 3, 5, 7],
                    values=[0.1, 0.2, 0.3, 0.4]
                )
            },
        )
    ],
)

Now you can run a search with sparse vectors:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

result = client.query_points(
    collection_name="{collection_name}",
    query=models.SparseVector(indices=[1, 3, 5, 7], values=[0.1, 0.2, 0.3, 0.4]),
    using="text",
).points

Multivectors
Available as of v1.10.0

Qdrant supports the storing of a variable amount of same-shaped dense vectors in a single point. This means that instead of a single dense vector, you can upload a matrix of dense vectors.

The length of the matrix is fixed, but the number of vectors in the matrix can be different for each point.

Multivectors look like this:

// A multivector of size 4
"vector": [
    [-0.013,  0.020, -0.007, -0.111],
    [-0.030, -0.055,  0.001,  0.072],
    [-0.041,  0.014, -0.032, -0.062],
    ....
]

There are two scenarios where multivectors are useful:

Multiple representation of the same object - For example, you can store multiple embeddings for pictures of the same object, taken from different angles. This approach assumes that the payload is same for all vectors.
Late interaction embeddings - Some text embedding models can output multiple vectors for a single text. For example, a family of models such as ColBERT output a relatively small vector for each token in the text.
In order to use multivectors, we need to specify a function that will be used to compare between matrices of vectors

Currently, Qdrant supports max_sim function, which is defined as a sum of maximum similarities between each pair of vectors in the matrices.


Where 
 is the number of vectors in the first matrix, 
 is the number of vectors in the second matrix, and 
 is a similarity function, for example, cosine similarity.

To use multivectors, create a collection with the following configuration:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.create_collection(
    collection_name="{collection_name}",
    vectors_config=models.VectorParams(
        size=128,
        distance=models.Distance.COSINE,
        multivector_config=models.MultiVectorConfig(
            comparator=models.MultiVectorComparator.MAX_SIM
        ),
    ),
)

To insert a point with multivector:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.upsert(
    collection_name="{collection_name}",
    points=[
        models.PointStruct(
            id=1,
            vector=[
                [-0.013,  0.020, -0.007, -0.111],
                [-0.030, -0.055,  0.001,  0.072],
                [-0.041,  0.014, -0.032, -0.062]
            ],
        )
    ],
)

To search with multivector (available in query API):

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.query_points(
    collection_name="{collection_name}",
    query=[
        [-0.013,  0.020, -0.007, -0.111],
        [-0.030, -0.055,  0.001,  0.072],
        [-0.041,  0.014, -0.032, -0.062]
    ],
)

Named Vectors
In Qdrant, you can store multiple vectors of different sizes and types in the same data point. This is useful when you need to define your data with multiple embeddings to represent different features or modalities (e.g., image, text or video).

To store different vectors for each point, you need to create separate named vector spaces in the collection. You can define these vector spaces during collection creation and manage them independently.

Each vector should have a unique name. Vectors can represent different modalities and you can use different embedding models to generate them.
To create a collection with named vectors, you need to specify a configuration for each vector:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.create_collection(
    collection_name="{collection_name}",
    vectors_config={
        "image": models.VectorParams(size=4, distance=models.Distance.DOT),
        "text": models.VectorParams(size=5, distance=models.Distance.COSINE),
    },
    sparse_vectors_config={"text-sparse": models.SparseVectorParams()},
)

To insert a point with named vectors:

http
python
typescript
rust
java
csharp
go
client.upsert(
    collection_name="{collection_name}",
    points=[
        models.PointStruct(
            id=1,
            vector={
                "image": [0.9, 0.1, 0.1, 0.2],
                "text": [0.4, 0.7, 0.1, 0.8, 0.1],
                "text-sparse": {
                    "indices": [1, 3, 5, 7],
                    "values": [0.1, 0.2, 0.3, 0.4],
                },
            },
        ),
    ],
)

To search with named vectors (available in query API):

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient

client = QdrantClient(url="http://localhost:6333")

client.query_points(
    collection_name="{collection_name}",
    query=[0.2, 0.1, 0.9, 0.7],
    using="image",
    limit=3,
)

Inference
Instead of providing vectors explicitly when ingesting or querying data, Qdrant can also generate vectors using a process called inference. Inference is the process of creating vector embeddings from text, images, or other data types using a machine learning model.

You can use inference in the API wherever you can use regular vectors. For example, while upserting points, you can provide the text or image and the embedding model:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(
    url="https://xyz-example.qdrant.io:6333", 
    api_key="<your-api-key>", 
    cloud_inference=True
)

client.upsert(
    collection_name="{collection_name}",
    points=[
        models.PointStruct(
            id=1,
            vector={
                "my-bm25-vector": models.Document(
                    text="Recipe for baking chocolate chip cookies",
                    model="Qdrant/bm25",
                )
            },
        )
    ],
)

Qdrant uses the model to generate the embeddings and store the point with the resulting vector.

Similarly, you can use inference at query time by providing the text or image to query with and the embedding model:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(
    url="https://xyz-example.qdrant.io:6333", 
    api_key="<your-api-key>", 
    cloud_inference=True
)

client.query_points(
    collection_name="{collection_name}",
    query=models.Document(
        text="How to bake cookies?", 
        model="Qdrant/bm25",
    ),
    using="my-bm25-vector",
)

Datatypes
Newest versions of embeddings models generate vectors with very large dimentionalities. With OpenAI’s text-embedding-3-large embedding model, the dimensionality can go up to 3072.

The amount of memory required to store such vectors grows linearly with the dimensionality, so it is important to choose the right datatype for the vectors.

The choice between datatypes is a trade-off between memory consumption and precision of vectors.

Qdrant supports a number of datatypes for both dense and sparse vectors:

Float32

This is the default datatype for vectors in Qdrant. It is a 32-bit (4 bytes) floating-point number. The standard OpenAI embedding of 1536 dimensionality will require 6KB of memory to store in Float32.

You don’t need to specify the datatype for vectors in Qdrant, as it is set to Float32 by default.

Float16

This is a 16-bit (2 bytes) floating-point number. It is also known as half-precision float. Intuitively, it looks like this:

float32 -> float16 delta (float32 - float16).abs

0.79701585 -> 0.796875   delta 0.00014084578
0.7850789  -> 0.78515625 delta 0.00007736683
0.7775044  -> 0.77734375 delta 0.00016063452
0.85776305 -> 0.85791016 delta 0.00014710426
0.6616839  -> 0.6616211  delta 0.000062823296

The main advantage of Float16 is that it requires half the memory of Float32, while having virtually no impact on the quality of vector search.

To use Float16, you need to specify the datatype for vectors in the collection configuration:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.create_collection(
    collection_name="{collection_name}",
    vectors_config=models.VectorParams(
        size=128,
        distance=models.Distance.COSINE,
        datatype=models.Datatype.FLOAT16
    ),
    sparse_vectors_config={
        "text": models.SparseVectorParams(
            index=models.SparseIndexParams(datatype=models.Datatype.FLOAT16)
        ),
    },
)

Uint8

Another step towards memory optimization is to use the Uint8 datatype for vectors. Unlike Float16, Uint8 is not a floating-point number, but an integer number in the range from 0 to 255.

Not all embeddings models generate vectors in the range from 0 to 255, so you need to be careful when using Uint8 datatype.

In order to convert a number from float range to Uint8 range, you need to apply a process called quantization.

Some embedding providers may provide embeddings in a pre-quantized format. One of the most notable examples is the Cohere int8 & binary embeddings.

For other embeddings, you will need to apply quantization yourself.

There is a difference in how Uint8 vectors are handled for dense and sparse vectors. Dense vectors are required to be in the range from 0 to 255, while sparse vectors can be quantized in-flight.
http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.create_collection(
    collection_name="{collection_name}",
    vectors_config=models.VectorParams(
        size=128, distance=models.Distance.COSINE, datatype=models.Datatype.UINT8
    ),
    sparse_vectors_config={
        "text": models.SparseVectorParams(
            index=models.SparseIndexParams(datatype=models.Datatype.UINT8)
        ),
    },
)

Quantization
Apart from changing the datatype of the original vectors, Qdrant can create quantized representations of vectors alongside the original ones. This quantized representation can be used to quickly select candidates for rescoring with the original vectors or even used directly for search.

Quantization is applied in the background, during the optimization process.

More information about the quantization process can be found in the Quantization section.

Vector Storage
Depending on the requirements of the application, Qdrant can use one of the data storage options. Keep in mind that you will have to tradeoff between search speed and the size of RAM used.

More information about the storage options can be found in the Storage section.









Payload
One of the significant features of Qdrant is the ability to store additional information along with vectors. This information is called payload in Qdrant terminology.

Qdrant allows you to store any information that can be represented using JSON.

Here is an example of a typical payload:

{
    "name": "jacket",
    "colors": ["red", "blue"],
    "count": 10,
    "price": 11.99,
    "locations": [
        {
            "lon": 52.5200, 
            "lat": 13.4050
        }
    ],
    "reviews": [
        {
            "user": "alice",
            "score": 4
        },
        {
            "user": "bob",
            "score": 5
        }
    ]
}

Payload types
In addition to storing payloads, Qdrant also allows you search based on certain kinds of values. This feature is implemented as additional filters during the search and will enable you to incorporate custom logic on top of semantic similarity.

During the filtering, Qdrant will check the conditions over those values that match the type of the filtering condition. If the stored value type does not fit the filtering condition - it will be considered not satisfied.

For example, you will get an empty output if you apply the range condition on the string data.

However, arrays (multiple values of the same type) are treated a little bit different. When we apply a filter to an array, it will succeed if at least one of the values inside the array meets the condition.

The filtering process is discussed in detail in the section Filtering.

Let’s look at the data types that Qdrant supports for searching:

Integer
integer - 64-bit integer in the range from -9223372036854775808 to 9223372036854775807.

Example of single and multiple integer values:

{
    "count": 10,
    "sizes": [35, 36, 38]
}

Float
float - 64-bit floating point number.

Example of single and multiple float values:

{
    "price": 11.99,
    "ratings": [9.1, 9.2, 9.4]
}

Bool
Bool - binary value. Equals to true or false.

Example of single and multiple bool values:

{
    "is_delivered": true,
    "responses": [false, false, true, false]
}

Keyword
keyword - string value.

Example of single and multiple keyword values:

{
    "name": "Alice",
    "friends": [
        "bob",
        "eva",
        "jack"
    ]
}

Geo
geo is used to represent geographical coordinates.

Example of single and multiple geo values:

{
    "location": {
        "lon": 52.5200,
        "lat": 13.4050
    },
    "cities": [
        {
            "lon": 51.5072,
            "lat": 0.1276
        },
        {
            "lon": 40.7128,
            "lat": 74.0060
        }
    ]
}

Coordinate should be described as an object containing two fields: lon - for longitude, and lat - for latitude.

Datetime
Available as of v1.8.0

datetime - date and time in RFC 3339 format.

See the following examples of single and multiple datetime values:

{
    "created_at": "2023-02-08T10:49:00Z",
    "updated_at": [
        "2023-02-08T13:52:00Z",
        "2023-02-21T21:23:00Z"
    ]
}

The following formats are supported:

"2023-02-08T10:49:00Z" (RFC 3339, UTC)
"2023-02-08T11:49:00+01:00" (RFC 3339, with timezone)
"2023-02-08T10:49:00" (without timezone, UTC is assumed)
"2023-02-08T10:49" (without timezone and seconds)
"2023-02-08" (only date, midnight is assumed)
Notes about the format:

T can be replaced with a space.
The T and Z symbols are case-insensitive.
UTC is always assumed when the timezone is not specified.
Timezone can have the following formats: ±HH:MM, ±HHMM, ±HH, or Z.
Seconds can have up to 6 decimals, so the finest granularity for datetime is microseconds.
UUID
Available as of v1.11.0

In addition to the basic keyword type, Qdrant supports uuid type for storing UUID values. Functionally, it works the same as keyword, internally stores parsed UUID values.

{
    "uuid": "550e8400-e29b-41d4-a716-446655440000",
    "uuids": [
        "550e8400-e29b-41d4-a716-446655440000",
        "550e8400-e29b-41d4-a716-446655440001"
    ]
}

String representation of UUID (e.g. 550e8400-e29b-41d4-a716-446655440000) occupies 36 bytes. But when numeric representation is used, it is only 128 bits (16 bytes).

Usage of uuid index type is recommended in payload-heavy collections to save RAM and improve search performance.

Create point with payload
REST API (Schema)

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.upsert(
    collection_name="{collection_name}",
    points=[
        models.PointStruct(
            id=1,
            vector=[0.05, 0.61, 0.76, 0.74],
            payload={
                "city": "Berlin",
                "price": 1.99,
            },
        ),
        models.PointStruct(
            id=2,
            vector=[0.19, 0.81, 0.75, 0.11],
            payload={
                "city": ["Berlin", "London"],
                "price": 1.99,
            },
        ),
        models.PointStruct(
            id=3,
            vector=[0.36, 0.55, 0.47, 0.94],
            payload={
                "city": ["Berlin", "Moscow"],
                "price": [1.99, 2.99],
            },
        ),
    ],
)

Update payload
Updating payloads in Qdrant offers flexible methods to manage vector metadata. The set payload method updates specific fields while keeping others unchanged, while the overwrite method replaces the entire payload. Developers can also use clear payload to remove all metadata or delete fields to remove specific keys without affecting the rest. These options provide precise control for adapting to dynamic datasets.

Set payload
Set only the given payload values on a point.

REST API (Schema):

http
python
typescript
rust
java
csharp
go
client.set_payload(
    collection_name="{collection_name}",
    payload={
        "property1": "string",
        "property2": "string",
    },
    points=[0, 3, 10],
)

You don’t need to know the ids of the points you want to modify. The alternative is to use filters.

http
python
typescript
rust
java
csharp
go
client.set_payload(
    collection_name="{collection_name}",
    payload={
        "property1": "string",
        "property2": "string",
    },
    points=models.Filter(
        must=[
            models.FieldCondition(
                key="color",
                match=models.MatchValue(value="red"),
            ),
        ],
    ),
)

Available as of v1.8.0

It is possible to modify only a specific key of the payload by using the key parameter.

For instance, given the following payload JSON object on a point:

{
    "property1": {
        "nested_property": "foo",
    },
    "property2": {
        "nested_property": "bar",
    }
}

You can modify the nested_property of property1 with the following request:

POST /collections/{collection_name}/points/payload
{
    "payload": {
        "nested_property": "qux",
    },
    "key": "property1",
    "points": [1]
}

Resulting in the following payload:

{
    "property1": {
        "nested_property": "qux",
    },
    "property2": {
        "nested_property": "bar",
    }
}

Overwrite payload
Fully replace any existing payload with the given one.

REST API (Schema):

http
python
typescript
rust
java
csharp
go
PUT /collections/{collection_name}/points/payload
{
    "payload": {
        "property1": "string",
        "property2": "string"
    },
    "points": [
        0, 3, 100
    ]
}

Like set payload, you don’t need to know the ids of the points you want to modify. The alternative is to use filters.

Clear payload
This method removes all payload keys from specified points

REST API (Schema):

http
python
typescript
rust
java
csharp
go
client.clear_payload(
    collection_name="{collection_name}",
    points_selector=[0, 3, 100],
)

You can also use models.FilterSelector to remove the points matching given filter criteria, instead of providing the ids.
Delete payload keys
Delete specific payload keys from points.

REST API (Schema):

http
python
typescript
rust
java
csharp
go
client.delete_payload(
    collection_name="{collection_name}",
    keys=["color", "price"],
    points=[0, 3, 100],
)

Alternatively, you can use filters to delete payload keys from the points.

http
python
typescript
rust
java
csharp
go
client.delete_payload(
    collection_name="{collection_name}",
    keys=["color", "price"],
    points=models.Filter(
        must=[
            models.FieldCondition(
                key="color",
                match=models.MatchValue(value="red"),
            ),
        ],
    ),
)

Payload indexing
To search more efficiently with filters, Qdrant allows you to create indexes for payload fields by specifying the name and type of field it is intended to be.

The indexed fields also affect the vector index. See Indexing for details.

In practice, we recommend creating an index on those fields that could potentially constrain the results the most. For example, using an index for the object ID will be much more efficient, being unique for each record, than an index by its color, which has only a few possible values.

In compound queries involving multiple fields, Qdrant will attempt to use the most restrictive index first.

To create index for the field, you can use the following:

REST API (Schema)

http
python
typescript
rust
java
csharp
go
client.create_payload_index(
    collection_name="{collection_name}",
    field_name="name_of_the_field_to_index",
    field_schema="keyword",
)

The index usage flag is displayed in the payload schema with the collection info API.

Payload schema example:

{
    "payload_schema": {
        "property1": {
            "data_type": "keyword"
        },
        "property2": {
            "data_type": "integer"
        }
    }
}

Facet counts
Available as of v1.12.0

Faceting is a special counting technique that can be used for various purposes:

Know which unique values exist for a payload key.
Know the number of points that contain each unique value.
Know how restrictive a filter would become by matching a specific value.
Specifically, it is a counting aggregation for the values in a field, akin to a GROUP BY with COUNT(*) commands in SQL.

These results for a specific field is called a “facet”. For example, when you look at an e-commerce search results page, you might see a list of brands on the sidebar, showing the number of products for each brand. This would be a facet for a "brand" field.

In Qdrant you can facet on a field only if you have created a field index that supports MatchValue conditions for it, like a keyword index.
To get the facet counts for a field, you can use the following:

By default, the number of hits returned is limited to 10. To change this, use the limit parameter. Keep this in mind when checking the number of unique values a payload field contains.
REST API (Facet)

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.facet(
    collection_name="{collection_name}",
    key="size",
    facet_filter=models.Filter(
        must=[
            models.FieldCondition(
                key="color",
                match=models.MatchValue(value="red"),
            )
        ]
    ),
)

The response will contain the counts for each unique value in the field:

{
  "response": {
    "hits": [
      {"value": "L", "count": 19},
      {"value": "S", "count": 10},
      {"value": "M", "count": 5},
      {"value": "XL", "count": 1},
      {"value": "XXL", "count": 1}
    ]
  },
  "time": 0.0001
}

The results are sorted by the count in descending order, then by the value in ascending order. Only values with non-zero counts will be returned.

By default, the way Qdrant the counts for each value is approximate to achieve fast results. This should accurate enough for most cases, but if you need to debug your storage, you can use the exact parameter to get exact counts.

http
python
typescript
rust
java
csharp
go
client.facet(
    collection_name="{collection_name}",
    key="size",
    exact=True,
)





Similarity search
Searching for the nearest vectors is at the core of many representational learning applications. Modern neural networks are trained to transform objects into vectors so that objects close in the real world appear close in vector space. It could be, for example, texts with similar meanings, visually similar pictures, or songs of the same genre.

This is how vector similarity works
This is how vector similarity works

Query API
Available as of v1.10.0

Qdrant provides a single interface for all kinds of search and exploration requests - the Query API. Here is a reference list of what kind of queries you can perform with the Query API in Qdrant:

Depending on the query parameter, Qdrant might prefer different strategies for the search.

Nearest Neighbors Search	Vector Similarity Search, also known as k-NN
Search By Id	Search by an already stored vector - skip embedding model inference
Recommendations	Provide positive and negative examples
Discovery Search	Guide the search using context as a one-shot training set
Scroll	Get all points with optional filtering
Grouping	Group results by a certain field
Order By	Order points by payload key
Hybrid Search	Combine multiple queries to get better results
Multi-Stage Search	Optimize performance for large embeddings
Random Sampling	Get random points from the collection
Nearest Neighbors Search

http
python
typescript
rust
java
csharp
go
client.query_points(
    collection_name="{collection_name}",
    query=[0.2, 0.1, 0.9, 0.7], # <--- Dense vector
)

Search By Id

http
python
typescript
rust
java
csharp
go
client.query_points(
    collection_name="{collection_name}",
    query="43cf51e2-8777-4f52-bc74-c2cbde0c8b04", # <--- point id
)

Metrics
There are many ways to estimate the similarity of vectors with each other. In Qdrant terms, these ways are called metrics. The choice of metric depends on the vectors obtained and, in particular, on the neural network encoder training method.

Qdrant supports these most popular types of metrics:

Dot product: Dot - https://en.wikipedia.org/wiki/Dot_product
Cosine similarity: Cosine - https://en.wikipedia.org/wiki/Cosine_similarity
Euclidean distance: Euclid - https://en.wikipedia.org/wiki/Euclidean_distance
Manhattan distance: Manhattan*- https://en.wikipedia.org/wiki/Taxicab_geometry *Available as of v1.7
The most typical metric used in similarity learning models is the cosine metric.

Embeddings

Qdrant counts this metric in 2 steps, due to which a higher search speed is achieved. The first step is to normalize the vector when adding it to the collection. It happens only once for each vector.

The second step is the comparison of vectors. In this case, it becomes equivalent to dot production - a very fast operation due to SIMD.

Depending on the query configuration, Qdrant might prefer different strategies for the search. Read more about it in the query planning section.

Search API
Let’s look at an example of a search query.

REST API - API Schema definition is available here

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.query_points(
    collection_name="{collection_name}",
    query=[0.2, 0.1, 0.9, 0.7],
    query_filter=models.Filter(
        must=[
            models.FieldCondition(
                key="city",
                match=models.MatchValue(
                    value="London",
                ),
            )
        ]
    ),
    search_params=models.SearchParams(hnsw_ef=128, exact=False),
    limit=3,
)

In this example, we are looking for vectors similar to vector [0.2, 0.1, 0.9, 0.7]. Parameter limit (or its alias - top) specifies the amount of most similar results we would like to retrieve.

Values under the key params specify custom parameters for the search. Currently, it could be:

hnsw_ef - value that specifies ef parameter of the HNSW algorithm.
exact - option to not use the approximate search (ANN). If set to true, the search may run for a long as it performs a full scan to retrieve exact results.
indexed_only - With this option you can disable the search in those segments where vector index is not built yet. This may be useful if you want to minimize the impact to the search performance whilst the collection is also being updated. Using this option may lead to a partial result if the collection is not fully indexed yet, consider using it only if eventual consistency is acceptable for your use case.
quantization - parameters related to quantization. See Searching with Quantization guide.
acorn - parameters related to the ACORN search algorithm.
Since the filter parameter is specified, the search is performed only among those points that satisfy the filter condition. See details of possible filters and their work in the filtering section.

Example result of this API would be

{
  "result": [
    { "id": 10, "score": 0.81 },
    { "id": 14, "score": 0.75 },
    { "id": 11, "score": 0.73 }
  ],
  "status": "ok",
  "time": 0.001
}

The result contains ordered by score list of found point ids.

Note that payload and vector data is missing in these results by default. See payload and vector in the result on how to include it.

If the collection was created with multiple vectors, the name of the vector to use for searching should be provided:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient

client = QdrantClient(url="http://localhost:6333")

client.query_points(
    collection_name="{collection_name}",
    query=[0.2, 0.1, 0.9, 0.7],
    using="image",
    limit=3,
)

Search is processing only among vectors with the same name.

If the collection was created with sparse vectors, the name of the sparse vector to use for searching should be provided:

You can still use payload filtering and other features of the search API with sparse vectors.

There are however important differences between dense and sparse vector search:

Index	Sparse Query	Dense Query
Scoring Metric	Default is Dot product, no need to specify it	Distance has supported metrics e.g. Dot, Cosine
Search Type	Always exact in Qdrant	HNSW is an approximate NN
Return Behaviour	Returns only vectors with non-zero values in the same indices as the query vector	Returns limit vectors
In general, the speed of the search is proportional to the number of non-zero values in the query vector.

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

result = client.query_points(
    collection_name="{collection_name}",
    query=models.SparseVector(indices=[1, 3, 5, 7], values=[0.1, 0.2, 0.3, 0.4]),
    using="text",
).points

Filtering results by score
In addition to payload filtering, it might be useful to filter out results with a low similarity score. For example, if you know the minimal acceptance score for your model and do not want any results which are less similar than the threshold. In this case, you can use score_threshold parameter of the search query. It will exclude all results with a score worse than the given.

This parameter may exclude lower or higher scores depending on the used metric. For example, higher scores of Euclidean metric are considered more distant and, therefore, will be excluded.
Payload and vector in the result
By default, retrieval methods do not return any stored information such as payload and vectors. Additional parameters with_vectors and with_payload alter this behavior.

Example:

http
python
typescript
rust
java
csharp
go
client.query_points(
    collection_name="{collection_name}",
    query=[0.2, 0.1, 0.9, 0.7],
    with_vectors=True,
    with_payload=True,
)

You can use with_payload to scope to or filter a specific payload subset. You can even specify an array of items to include, such as city, village, and town:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient

client = QdrantClient(url="http://localhost:6333")

client.query_points(
    collection_name="{collection_name}",
    query=[0.2, 0.1, 0.9, 0.7],
    with_payload=["city", "village", "town"],
)

Or use include or exclude explicitly. For example, to exclude city:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.query_points(
    collection_name="{collection_name}",
    query=[0.2, 0.1, 0.9, 0.7],
    with_payload=models.PayloadSelectorExclude(
        exclude=["city"],
    ),
)

It is possible to target nested fields using a dot notation:

payload.nested_field - for a nested field
payload.nested_array[].sub_field - for projecting nested fields within an array
Accessing array elements by index is currently not supported.

ACORN Search Algorithm
Available as of v1.16.0

For filtered vector search, you are recommended to create a payload index for the fields you want to filter by. During the search, Qdrant will use a combined filterable index. However, when combining multiple strict payload filters, this mechanism might not provide sufficient accuracy. In such cases, you can use the ACORN search algorithm.

It is an extension to the regular HNSW search algorithm, based on the ACORN-1 algorithm described in the paper ACORN: Performant and Predicate-Agnostic Search Over Vector Embeddings and Structured Data. During graph traversal, it explores not just direct neighbors (first hop), but also neighbors of neighbors (second hop) when direct neighbors are filtered out. This improves search accuracy at the cost of performance.

Enable it as follows:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.query_points(
    collection_name="{collection_name}",
    query=[0.2, 0.1, 0.9, 0.7],
    search_params=models.SearchParams(
        acorn=models.AcornSearchParams(
            enable=True,
            max_selectivity=0.4,
        )
    ),
    limit=10,
)

ACORN is disabled by default. Once enabled via the enable flag, it activates conditionally when estimated filter selectivity is below the threshold. The optional max_selectivity value controls this threshold; 0.0 means ACORN will never be used, 1.0 means it will always be used. The default value is 0.4. Selectivity is estimated as:
 
Since ACORN is significantly slower (approximately 2-10x in typical scenarios) but improves recall for restrictive filters, tuning this parameter is about deciding when the accuracy improvement justifies the performance cost.

Batch search API
The batch search API enables to perform multiple search requests via a single request.

Its semantic is straightforward, n batched search requests are equivalent to n singular search requests.

This approach has several advantages. Logically, fewer network connections are required which can be very beneficial on its own.

More importantly, batched requests will be efficiently processed via the query planner which can detect and optimize requests if they have the same filter.

This can have a great effect on latency for non trivial filters as the intermediary results can be shared among the request.

In order to use it, simply pack together your search requests. All the regular attributes of a search request are of course available.

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

filter_ = models.Filter(
    must=[
        models.FieldCondition(
            key="city",
            match=models.MatchValue(
                value="London",
            ),
        )
    ]
)

search_queries = [
    models.QueryRequest(query=[0.2, 0.1, 0.9, 0.7], filter=filter_, limit=3),
    models.QueryRequest(query=[0.5, 0.3, 0.2, 0.3], filter=filter_, limit=3),
]

client.query_batch_points(collection_name="{collection_name}", requests=search_queries)

The result of this API contains one array per search requests.

{
  "result": [
    [
        { "id": 10, "score": 0.81 },
        { "id": 14, "score": 0.75 },
        { "id": 11, "score": 0.73 }
    ],
    [
        { "id": 1, "score": 0.92 },
        { "id": 3, "score": 0.89 },
        { "id": 9, "score": 0.75 }
    ]
  ],
  "status": "ok",
  "time": 0.001
}

Query by ID
Whenever you need to use a vector as an input, you can always use a point ID instead.

http
python
typescript
rust
java
csharp
go
client.query_points(
    collection_name="{collection_name}",
    query="43cf51e2-8777-4f52-bc74-c2cbde0c8b04", # <--- point id
)

The above example will fetch the default vector from the point with this id, and use it as the query vector.

If the using parameter is also specified, Qdrant will use the vector with that name.

It is also possible to reference an ID from a different collection, by setting the lookup_from parameter.

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.query_points(
    collection_name="{collection_name}",
    query="43cf51e2-8777-4f52-bc74-c2cbde0c8b04",  # <--- point id
    using="512d-vector",
    lookup_from=models.LookupLocation(
        collection="another_collection",  # <--- other collection name
        vector="image-512",  # <--- vector name in the other collection
    )
)

In the case above, Qdrant will fetch the "image-512" vector from the specified point id in the collection another_collection.

The fetched vector(s) must match the characteristics of the using vector, otherwise, an error will be returned.
Pagination
Search and recommendation APIs allow to skip first results of the search and return only the result starting from some specified offset:

Example:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient

client = QdrantClient(url="http://localhost:6333")

client.query_points(
    collection_name="{collection_name}",
    query=[0.2, 0.1, 0.9, 0.7],
    with_vectors=True,
    with_payload=True,
    limit=10,
    offset=100,
)

Is equivalent to retrieving the 11th page with 10 records per page.

Large offset values may cause performance issues
Vector-based retrieval in general and HNSW index in particular, are not designed to be paginated. It is impossible to retrieve Nth closest vector without retrieving the first N vectors first.

However, using the offset parameter saves the resources by reducing network traffic and the number of times the storage is accessed.

Using an offset parameter, will require to internally retrieve offset + limit points, but only access payload and vector from the storage those points which are going to be actually returned.

Grouping API
It is possible to group results by a certain field. This is useful when you have multiple points for the same item, and you want to avoid redundancy of the same item in the results.

For example, if you have a large document split into multiple chunks, and you want to search or recommend on a per-document basis, you can group the results by the document ID.

Consider having points with the following payloads:

[
    {
        "id": 0,
        "payload": {
            "chunk_part": 0, 
            "document_id": "a"
        },
        "vector": [0.91]
    },
    {
        "id": 1,
        "payload": {
            "chunk_part": 1, 
            "document_id": ["a", "b"]
        },
        "vector": [0.8]
    },
    {
        "id": 2,
        "payload": {
            "chunk_part": 2, 
            "document_id": "a"
        },
        "vector": [0.2]
    },
    {
        "id": 3,
        "payload": {
            "chunk_part": 0, 
            "document_id": 123
        },
        "vector": [0.79]
    },
    {
        "id": 4,
        "payload": {
            "chunk_part": 1, 
            "document_id": 123
        },
        "vector": [0.75]
    },
    {
        "id": 5,
        "payload": {
            "chunk_part": 0, 
            "document_id": -10
        },
        "vector": [0.6]
    }
]

With the groups API, you will be able to get the best N points for each document, assuming that the payload of the points contains the document ID. Of course there will be times where the best N points cannot be fulfilled due to lack of points or a big distance with respect to the query. In every case, the group_size is a best-effort parameter, akin to the limit parameter.

Search groups
REST API (Schema):

http
python
typescript
rust
java
csharp
go
client.query_points_groups(
    collection_name="{collection_name}",
    # Same as in the regular query_points() API
    query=[1.1],
    # Grouping parameters
    group_by="document_id",  # Path of the field to group by
    limit=4,  # Max amount of groups
    group_size=2,  # Max amount of points per group
)

The output of a groups call looks like this:

{
    "result": {
        "groups": [
            {
                "id": "a",
                "hits": [
                    { "id": 0, "score": 0.91 },
                    { "id": 1, "score": 0.85 }
                ]
            },
            {
                "id": "b",
                "hits": [
                    { "id": 1, "score": 0.85 }
                ]
            },
            {
                "id": 123,
                "hits": [
                    { "id": 3, "score": 0.79 },
                    { "id": 4, "score": 0.75 }
                ]
            },
            {
                "id": -10,
                "hits": [
                    { "id": 5, "score": 0.6 }
                ]
            }
        ]
    },
    "status": "ok",
    "time": 0.001
}

The groups are ordered by the score of the top point in the group. Inside each group the points are sorted too.

If the group_by field of a point is an array (e.g. "document_id": ["a", "b"]), the point can be included in multiple groups (e.g. "document_id": "a" and document_id: "b").

This feature relies heavily on the `group_by` key provided. To improve performance, make sure to create a dedicated index for it.
Limitations:

Only keyword and integer payload values are supported for the group_by parameter. Payload values with other types will be ignored.
At the moment, pagination is not enabled when using groups, so the offset parameter is not allowed.
Lookup in groups
Having multiple points for parts of the same item often introduces redundancy in the stored data. Which may be fine if the information shared by the points is small, but it can become a problem if the payload is large, because it multiplies the storage space needed to store the points by a factor of the amount of points we have per group.

One way of optimizing storage when using groups is to store the information shared by the points with the same group id in a single point in another collection. Then, when using the groups API, add the with_lookup parameter to bring the information from those points into each group.

Group id matches point id

Store only document-level metadata (e.g., titles, abstracts) in the lookup collection, not chunks or duplicated data.
This has the extra benefit of having a single point to update when the information shared by the points in a group changes.

For example, if you have a collection of documents, you may want to chunk them and store the points for the chunks in a separate collection, making sure that you store the point id from the document it belongs in the payload of the chunk point.

In this case, to bring the information from the documents into the chunks grouped by the document id, you can use the with_lookup parameter:

http
python
typescript
rust
java
csharp
go
client.query_points_groups(
    collection_name="chunks",
    # Same as in the regular search() API
    query=[1.1],
    # Grouping parameters
    group_by="document_id",  # Path of the field to group by
    limit=2,  # Max amount of groups
    group_size=2,  # Max amount of points per group
    # Lookup parameters
    with_lookup=models.WithLookup(
        # Name of the collection to look up points in
        collection="documents",
        # Options for specifying what to bring from the payload
        # of the looked up point, True by default
        with_payload=["title", "text"],
        # Options for specifying what to bring from the vector(s)
        # of the looked up point, True by default
        with_vectors=False,
    ),
)

For the with_lookup parameter, you can also use the shorthand with_lookup="documents" to bring the whole payload and vector(s) without explicitly specifying it.

The looked up result will show up under lookup in each group.

{
    "result": {
        "groups": [
            {
                "id": 1,
                "hits": [
                    { "id": 0, "score": 0.91 },
                    { "id": 1, "score": 0.85 }
                ],
                "lookup": {
                    "id": 1,
                    "payload": {
                        "title": "Document A",
                        "text": "This is document A"
                    }
                }
            },
            {
                "id": 2,
                "hits": [
                    { "id": 1, "score": 0.85 }
                ],
                "lookup": {
                    "id": 2,
                    "payload": {
                        "title": "Document B",
                        "text": "This is document B"
                    }
                }
            }
        ]
    },
    "status": "ok",
    "time": 0.001
}

Since the lookup is done by matching directly with the point id, the lookup collection must be pre-populated with points where the id matches the group_by value (e.g., document_id) from your primary collection.

Any group id that is not an existing (and valid) point id in the lookup collection will be ignored, and the lookup field will be empty.

Random Sampling
Available as of v1.11.0

In some cases it might be useful to retrieve a random sample of points from the collection. This can be useful for debugging, testing, or for providing entry points for exploration.

Random sampling API is a part of Universal Query API and can be used in the same way as regular search API.

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

sampled = client.query_points(
    collection_name="{collection_name}",
    query=models.SampleQuery(sample=models.Sample.RANDOM)
)

Query planning
Depending on the filter used in the search - there are several possible scenarios for query execution. Qdrant chooses one of the query execution options depending on the available indexes, the complexity of the conditions and the cardinality of the filtering result. This process is called query planning.

The strategy selection process relies heavily on heuristics and can vary from release to release. However, the general principles are:

planning is performed for each segment independently (see storage for more information about segments)
prefer a full scan if the amount of points is below a threshold
estimate the cardinality of a filtered result before selecting a strategy
retrieve points using payload index (see indexing) if cardinality is below threshold
use filterable vector index if the cardinality is above a threshold
use ACORN when the selectivity (ratio) is low, but the cardinality (an amount) is still high
You can adjust the threshold using a configuration file, as well as independently for each collection.






Explore the data
After mastering the concepts in search, you can start exploring your data in other ways. Qdrant provides a stack of APIs that allow you to find similar vectors in a different fashion, as well as to find the most dissimilar ones. These are useful tools for recommendation systems, data exploration, and data cleaning.

Recommendation API
In addition to the regular search, Qdrant also allows you to search based on multiple positive and negative examples. The API is called recommend, and the examples can be point IDs, so that you can leverage the already encoded objects; and, as of v1.6, you can also use raw vectors as input, so that you can create your vectors on the fly without uploading them as points.

REST API - API Schema definition is available here

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.query_points(
    collection_name="{collection_name}",
    query=models.RecommendQuery(
        recommend=models.RecommendInput(
            positive=[100, 231],
            negative=[718, [0.2, 0.3, 0.4, 0.5]],
            strategy=models.RecommendStrategy.AVERAGE_VECTOR,
        )
    ),
    query_filter=models.Filter(
        must=[
            models.FieldCondition(
                key="city",
                match=models.MatchValue(
                    value="London",
                ),
            )
        ]
    ),
    limit=3,
)

Example result of this API would be

{
  "result": [
    { "id": 10, "score": 0.81 },
    { "id": 14, "score": 0.75 },
    { "id": 11, "score": 0.73 }
  ],
  "status": "ok",
  "time": 0.001
}

The algorithm used to get the recommendations is selected from the available strategy options. Each of them has its own strengths and weaknesses, so experiment and choose the one that works best for your case.

Average vector strategy
The default and first strategy added to Qdrant is called average_vector. It preprocesses the input examples to create a single vector that is used for the search. Since the preprocessing step happens very fast, the performance of this strategy is on-par with regular search. The intuition behind this kind of recommendation is that each vector component represents an independent feature of the data, so, by averaging the examples, we should get a good recommendation.

The way to produce the searching vector is by first averaging all the positive and negative examples separately, and then combining them into a single vector using the following formula:

avg_positive + avg_positive - avg_negative

In the case of not having any negative examples, the search vector will simply be equal to avg_positive.

This is the default strategy that’s going to be set implicitly, but you can explicitly define it by setting "strategy": "average_vector" in the recommendation request.

Best score strategy
Available as of v1.6.0

A new strategy introduced in v1.6, is called best_score. It is based on the idea that the best way to find similar vectors is to find the ones that are closer to a positive example, while avoiding the ones that are closer to a negative one. The way it works is that each candidate is measured against every example, then we select the best positive and best negative scores. The final score is chosen with this step formula:

// Sigmoid function to normalize the score between 0 and 1
let sigmoid = |x| 0.5 * (1.0 + (x / (1.0 + x.abs())));

let score = if best_positive_score > best_negative_score {
    sigmoid(best_positive_score)
} else {
    -sigmoid(best_negative_score)
};

The performance of best_score strategy will be linearly impacted by the amount of examples.
Since we are computing similarities to every example at each step of the search, the performance of this strategy will be linearly impacted by the amount of examples. This means that the more examples you provide, the slower the search will be. However, this strategy can be very powerful and should be more embedding-agnostic.

Accuracy may be impacted with this strategy. To improve it, increasing the ef search parameter to something above 32 will already be much better than the default 16, e.g: "params": { "ef": 64 }
To use this algorithm, you need to set "strategy": "best_score" in the recommendation request.

Using only negative examples
A beneficial side-effect of best_score strategy is that you can use it with only negative examples. This will allow you to find the most dissimilar vectors to the ones you provide. This can be useful for finding outliers in your data, or for finding the most dissimilar vectors to a given one.

Combining negative-only examples with filtering can be a powerful tool for data exploration and cleaning.

Sum scores strategy
Another strategy for using multiple query vectors simultaneously is to just sum their scores against the candidates. In qdrant, this is called sum_scores strategy.

This strategy was used in this paper by UKP Lab, hessian.ai and cohere.ai to incorporate relevance feedback into a subsequent search. In the paper this boosted the nDCG@20 performance by 5.6% points when using 2-8 positive feedback documents.

The formula that this strategy implements is

  
 

where 
 is the set of positive examples, 
 is the set of negative examples, and 
 is the score of the vector 
 against the vector 

As with best_score, this strategy also allows using only negative examples.

Multiple vectors
Available as of v0.10.0

If the collection was created with multiple vectors, the name of the vector should be specified in the recommendation request:

http
python
typescript
rust
java
csharp
go
client.query_points(
    collection_name="{collection_name}",
    query=models.RecommendQuery(
        recommend=models.RecommendInput(
            positive=[100, 231],
            negative=[718],
        )
    ),
    using="image",
    limit=10,
)

Parameter using specifies which stored vectors to use for the recommendation.

Lookup vectors from another collection
Available as of v0.11.6

If you have collections with vectors of the same dimensionality, and you want to look for recommendations in one collection based on the vectors of another collection, you can use the lookup_from parameter.

It might be useful, e.g. in the item-to-user recommendations scenario. Where user and item embeddings, although having the same vector parameters (distance type and dimensionality), are usually stored in different collections.

http
python
typescript
rust
java
csharp
go
POST /collections/{collection_name}/points/query
{
  "query": {
    "recommend": {
      "positive": [100, 231],
      "negative": [718]
    }
  },
  "limit": 10,
  "lookup_from": {
    "collection": "{external_collection_name}",
    "vector": "{external_vector_name}"
  }
}

Vectors are retrieved from the external collection by ids provided in the positive and negative lists. These vectors then used to perform the recommendation in the current collection, comparing against the “using” or default vector.

Batch recommendation API
Available as of v0.10.0

Similar to the batch search API in terms of usage and advantages, it enables the batching of recommendation requests.

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

filter_ = models.Filter(
    must=[
        models.FieldCondition(
            key="city",
            match=models.MatchValue(
                value="London",
            ),
        )
    ]
)

recommend_queries = [
    models.QueryRequest(
        query=models.RecommendQuery(
            recommend=models.RecommendInput(positive=[100, 231], negative=[718])
        ),
        filter=filter_,
        limit=3,
    ),
    models.QueryRequest(
        query=models.RecommendQuery(
            recommend=models.RecommendInput(positive=[200, 67], negative=[300])
        ),
        filter=filter_,
        limit=3,
    ),
]

client.query_batch_points(
    collection_name="{collection_name}", requests=recommend_queries
)

The result of this API contains one array per recommendation requests.

{
  "result": [
    [
        { "id": 10, "score": 0.81 },
        { "id": 14, "score": 0.75 },
        { "id": 11, "score": 0.73 }
    ],
    [
        { "id": 1, "score": 0.92 },
        { "id": 3, "score": 0.89 },
        { "id": 9, "score": 0.75 }
    ]
  ],
  "status": "ok",
  "time": 0.001
}

Discovery API
Available as of v1.7

REST API Schema definition available here

In this API, Qdrant introduces the concept of context, which is used for splitting the space. Context is a set of positive-negative pairs, and each pair divides the space into positive and negative zones. In that mode, the search operation prefers points based on how many positive zones they belong to (or how much they avoid negative zones).

The interface for providing context is similar to the recommendation API (ids or raw vectors). Still, in this case, they need to be provided in the form of positive-negative pairs.

Discovery API lets you do two new types of search:

Discovery search: Uses the context (the pairs of positive-negative vectors) and a target to return the points more similar to the target, but constrained by the context.
Context search: Using only the context pairs, get the points that live in the best zone, where loss is minimized
The way positive and negative examples should be arranged in the context pairs is completely up to you. So you can have the flexibility of trying out different permutation techniques based on your model and data.

The speed of search is linearly related to the amount of examples you provide in the query.
Discovery search
This type of search works specially well for combining multimodal, vector-constrained searches. Qdrant already has extensive support for filters, which constrain the search based on its payload, but using discovery search, you can also constrain the vector space in which the search is performed.

Discovery search

The formula for the discovery score can be expressed as:

 
where 
 represents a positive example, 
 represents a negative example, and 
 is the similarity score of a vector 
 to the target vector. The discovery score is then computed as:
where 
 is the similarity function, 
 is the target vector, and again 
 and 
 are the positive and negative examples, respectively. The sigmoid function is used to normalize the score between 0 and 1 and the sum of ranks is used to penalize vectors that are closer to the negative examples than to the positive ones. In other words, the sum of individual ranks determines how many positive zones a point is in, while the closeness hierarchy comes second.

Example:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

discover_queries = [
    models.QueryRequest(
        query=models.DiscoverQuery(
            discover=models.DiscoverInput(
                target=[0.2, 0.1, 0.9, 0.7],
                context=[
                    models.ContextPair(
                        positive=100,
                        negative=718,
                    ),
                    models.ContextPair(
                        positive=200,
                        negative=300,
                    ),
                ],
            )
        ),
        limit=10,
    ),
]

client.query_batch_points(
    collection_name="{collection_name}", requests=discover_queries
)

Notes about discovery search:
When providing ids as examples, they will be excluded from the results.
Score is always in descending order (larger is better), regardless of the metric used.
Since the space is hard-constrained by the context, accuracy is normal to drop when using default settings. To mitigate this, increasing the ef search parameter to something above 64 will already be much better than the default 16, e.g: "params": { "ef": 128 }
Context search
Conversely, in the absence of a target, a rigid integer-by-integer function doesn’t provide much guidance for the search when utilizing a proximity graph like HNSW. Instead, context search employs a function derived from the triplet-loss concept, which is usually applied during model training. For context search, this function is adapted to steer the search towards areas with fewer negative examples.

Context search

We can directly associate the score function to a loss function, where 0.0 is the maximum score a point can have, which means it is only in positive areas. As soon as a point exists closer to a negative example, its loss will simply be the difference of the positive and negative similarities.


Where 
 and 
 are the positive and negative examples of each pair, and 
 is the similarity function.

Using this kind of search, you can expect the output to not necessarily be around a single point, but rather, to be any point that isn’t closer to a negative example, which creates a constrained diverse result. So, even when the API is not called recommend, recommendation systems can also use this approach and adapt it for their specific use-cases.

Example:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

discover_queries = [
    models.QueryRequest(
        query=models.ContextQuery(
            context=[
                models.ContextPair(
                    positive=100,
                    negative=718,
                ),
                models.ContextPair(
                    positive=200,
                    negative=300,
                ),
            ],
        ),
        limit=10,
    ),
]

client.query_batch_points(
    collection_name="{collection_name}", requests=discover_queries
)

Notes about context search:
When providing ids as examples, they will be excluded from the results.
Score is always in descending order (larger is better), regardless of the metric used.
Best possible score is 0.0, and it is normal that many points get this score.
Distance Matrix
Available as of v1.12.0

The distance matrix API allows to calculate the distance between sampled pairs of vectors and to return the result as a sparse matrix.

Such API enables new data exploration use cases such as clustering similar vectors, visualization of connections or dimension reduction.

The API input request consists of the following parameters:

sample: the number of vectors to sample
limit: the number of scores to return per sample
filter: the filter to apply to constraint the samples
Let’s have a look at a basic example with sample=100, limit=10:

The engine starts by selecting 100 random points from the collection, then for each of the selected points, it will compute the top 10 closest points within the samples.

This will results in a total of 1000 scores represented as a sparse matrix for efficient processing.

The distance matrix API offers two output formats to ease the integration with different tools.

Pairwise format
Returns the distance matrix as a list of pairs of point ids with their respective score.

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.search_matrix_pairs(
    collection_name="{collection_name}",
    sample=10,
    limit=2,
    query_filter=models.Filter(
        must=[
            models.FieldCondition(
                key="color", match=models.MatchValue(value="red")
            ),
        ]
    ),
)

Returns

{
    "result": {
        "pairs": [
            {"a": 1, "b": 3, "score": 1.4063001},
            {"a": 1, "b": 4, "score": 1.2531},
            {"a": 2, "b": 1, "score": 1.1550001},
            {"a": 2, "b": 8, "score": 1.1359},
            {"a": 3, "b": 1, "score": 1.4063001},
            {"a": 3, "b": 4, "score": 1.2218001},
            {"a": 4, "b": 1, "score": 1.2531},
            {"a": 4, "b": 3, "score": 1.2218001},
            {"a": 5, "b": 3, "score": 0.70239997},
            {"a": 5, "b": 1, "score": 0.6146},
            {"a": 6, "b": 3, "score": 0.6353},
            {"a": 6, "b": 4, "score": 0.5093},
            {"a": 7, "b": 3, "score": 1.0990001},
            {"a": 7, "b": 1, "score": 1.0349001},
            {"a": 8, "b": 2, "score": 1.1359},
            {"a": 8, "b": 3, "score": 1.0553}
        ]
    }
}

Offset format
Returns the distance matrix as a four arrays:

offsets_row and offsets_col, represent the positions of non-zero distance values in the matrix.
scores contains the distance values.
ids contains the point ids corresponding to the distance values.
http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.search_matrix_offsets(
    collection_name="{collection_name}",
    sample=10,
    limit=2,
    query_filter=models.Filter(
        must=[
            models.FieldCondition(
                key="color", match=models.MatchValue(value="red")
            ),
        ]
    ),
)

Returns

{
    "result": {
        "offsets_row": [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7],
        "offsets_col": [2, 3, 0, 7, 0, 3, 0, 2, 2, 0, 2, 3, 2, 0, 1, 2],
        "scores": [
            1.4063001, 1.2531, 1.1550001, 1.1359, 1.4063001,
            1.2218001, 1.2531, 1.2218001, 0.70239997, 0.6146, 0.6353,
            0.5093, 1.0990001, 1.0349001, 1.1359, 1.0553
            ],
        "ids": [1, 2, 3, 4, 5, 6, 7, 8]
    }
}




Hybrid and Multi-Stage Queries
Available as of v1.10.0

With the introduction of multiple named vectors per point, there are use-cases when the best search is obtained by combining multiple queries, or by performing the search in more than one stage.

Qdrant has a flexible and universal interface to make this possible, called Query API (API reference).

The main component for making the combinations of queries possible is the prefetch parameter, which enables making sub-requests.

Specifically, whenever a query has at least one prefetch, Qdrant will:

Perform the prefetch query (or queries),
Apply the main query over the results of its prefetch(es).
Additionally, prefetches can have prefetches themselves, so you can have nested prefetches.

Using offset parameter only affects the main query. This means that the prefetches must have a limit of at least limit + offset of the main query, otherwise you can get an empty result.
Hybrid Search
One of the most common problems when you have different representations of the same data is to combine the queried points for each representation into a single result.

Fusing results from multiple queries
Fusing results from multiple queries

For example, in text search, it is often useful to combine dense and sparse vectors to get the best of both worlds: semantic understanding from dense vectors and precise word matching from sparse vectors.

Qdrant has a few ways of fusing the results from different queries: rrf and dbsf

Reciprocal Rank Fusion (RRF)
RRF considers the positions of results within each query, and boosts the ones that appear closer to the top in multiple sets of results.
The formula is simple, but needs access to the rank of each result in each query.

 
 

Where 
 the set of points across all results, 
 is the set of rankings for a particular document, and 
 is a constant (set to 2 by default).

Here is an example of RRF for a query containing two prefetches against different named vectors configured to hold sparse and dense vectors, respectively.

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.query_points(
    collection_name="{collection_name}",
    prefetch=[
        models.Prefetch(
            query=models.SparseVector(indices=[1, 42], values=[0.22, 0.8]),
            using="sparse",
            limit=20,
        ),
        models.Prefetch(
            query=[0.01, 0.45, 0.67],  # <-- dense vector
            using="dense",
            limit=20,
        ),
    ],
    query=models.FusionQuery(fusion=models.Fusion.RRF),
)

Parametrized RRF
Available as of v1.16.0

To change the value of constant 
 in the formula, use the dedicated rrf query variant.

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.query_points(
    collection_name="{collection_name}",
    prefetch=[
        # 2+ prefetches here
    ],
    query=models.RrfQuery(rrf=models.Rrf(k=60)),
)

Distribution-Based Score Fusion (DBSF)
Available as of v1.11.0

DBSF normalizes the scores of the points in each query, using the mean +/- the 3rd standard deviation as limits, and then sums the scores of the same point across different queries.
dbsf is stateless and calculates the normalization limits only based on the results of each query, not on all the scores that it has seen.
Multi-stage queries
In general, larger vector representations give more accurate search results, but makes them more expensive to compute.

Splitting the search into two stages is a known technique to mitigate this effect:

First, use a smaller and cheaper representation to get a large list of candidates.
Then, re-score the candidates using the larger and more accurate representation.
There are a few ways to build search architectures around this idea:

The quantized vectors as a first stage, and the full-precision vectors as a second stage.
Leverage Matryoshka Representation Learning (MRL) to generate candidate vectors with a shorter vector, and then refine them with a longer one.
Use regular dense vectors to pre-fetch the candidates, and then re-score them with a multi-vector model like ColBERT.
To get the best of all worlds, Qdrant has a convenient interface to perform the queries in stages, such that the coarse results are fetched first, and then they are refined later with larger vectors.

Re-scoring examples
Fetch 1000 results using a shorter MRL byte vector, then re-score them using the full vector and get the top 10.

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.query_points(
    collection_name="{collection_name}",
    prefetch=models.Prefetch(
        query=[1, 23, 45, 67],  # <------------- small byte vector
        using="mrl_byte",
        limit=1000,
    ),
    query=[0.01, 0.299, 0.45, 0.67],  # <-- full vector
    using="full",
    limit=10,
)

Fetch 100 results using the default vector, then re-score them using a multi-vector to get the top 10.

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.query_points(
    collection_name="{collection_name}",
    prefetch=models.Prefetch(
        query=[0.01, 0.45, 0.67, 0.53],  # <-- dense vector
        limit=100,
    ),
    query=[
        [0.1, 0.2, 0.32],  # <─┐
        [0.2, 0.1, 0.52],  # < ├─ multi-vector
        [0.8, 0.9, 0.93],  # < ┘
    ],
    using="colbert",
    limit=10,
)

It is possible to combine all the above techniques in a single query:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.query_points(
    collection_name="{collection_name}",
    prefetch=models.Prefetch(
        prefetch=models.Prefetch(
            query=[1, 23, 45, 67],  # <------ small byte vector
            using="mrl_byte",
            limit=1000,
        ),
        query=[0.01, 0.45, 0.67],  # <-- full dense vector
        using="full",
        limit=100,
    ),
    query=[
        [0.17, 0.23, 0.52],  # <─┐
        [0.22, 0.11, 0.63],  # < ├─ multi-vector
        [0.86, 0.93, 0.12],  # < ┘
    ],
    using="colbert",
    limit=10,
)

Maximal Marginal Relevance (MMR)
Available as of v1.15.0

A useful algorithm to improve the diversity of the results is Maximal Marginal Relevance (MMR). It excels when the dataset has many redundant or very similar points for a query.

MMR selects candidates iteratively, starting with the most relevant point (higher similarity to the query). For each next point, it selects the one that hasn’t been chosen yet which has the best combination of relevance and higher separation to the already selected points.

  
 

Where 
 is the candidates set, 
 is the selected set, 
 is the query vector, 
 is the similarity function, and 
.

This is implemented in Qdrant as a parameter of a nearest neighbors query. You define the vector to get the nearest candidates, and a diversity parameter which controls the balance between relevance (0.0) and diversity (1.0).

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.query_points(
    collection_name="{collection_name}",
    query=models.NearestQuery(
        nearest=[0.01, 0.45, 0.67], # search vector
        mmr=models.Mmr(
            diversity=0.5, # 0.0 - relevance; 1.0 - diversity
            candidates_limit=100, # num of candidates to preselect
        )
    ),
    limit=10,
)

Caveat: Since MMR ranks one point at a time, the scores produced by MMR in Qdrant refer to the similarity to the query vector. This means that the response will not be ordered by score, but rather by the order of selection of MMR.

Score boosting
Available as of v1.14.0

When introducing vector search to specific applications, sometimes business logic needs to be considered for ranking the final list of results.

A quick example is our own documentation search bar. It has vectors for every part of the documentation site. If one were to perform a search by “just” using the vectors, all kinds of elements would be equally considered good results. However, when searching for documentation, we can establish a hierarchy of importance:

title > content > snippets

One way to solve this is to weight the results based on the kind of element. For example, we can assign a higher weight to titles and content, and keep snippets unboosted.

Pseudocode would be something like:

score = score + (is_title * 0.5) + (is_content * 0.25)

Query API can rescore points with custom formulas. They can be based on:

Dynamic payload values
Conditions
Scores of prefetches
To express the formula, the syntax uses objects to identify each element. Taking the documentation example, the request would look like this:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

tag_boosted = client.query_points(
    collection_name="{collection_name}",
    prefetch=models.Prefetch(
        query=[0.1, 0.45, 0.67],  # <-- dense vector
        limit=50
    ),
    query=models.FormulaQuery(
        formula=models.SumExpression(sum=[
            "$score",
            models.MultExpression(mult=[0.5, models.FieldCondition(key="tag", match=models.MatchAny(any=["h1", "h2", "h3", "h4"]))]),
            models.MultExpression(mult=[0.25, models.FieldCondition(key="tag", match=models.MatchAny(any=["p", "li"]))])
        ]
    ))
)

There are multiple expressions available, check the API docs for specific details.

constant - A floating point number. e.g. 0.5.
"$score" - Reference to the score of the point in the prefetch. This is the same as "$score[0]".
"$score[0]", "$score[1]", "$score[2]", … - When using multiple prefetches, you can reference specific prefetch with the index within the array of prefetches.
payload key - Any plain string will refer to a payload key. This uses the jsonpath format used in every other place, e.g. key or key.subkey. It will try to extract a number from the given key.
condition - A filtering condition. If the condition is met, it becomes 1.0, otherwise 0.0.
mult - Multiply an array of expressions.
sum - Sum an array of expressions.
div - Divide an expression by another expression.
abs - Absolute value of an expression.
pow - Raise an expression to the power of another expression.
sqrt - Square root of an expression.
log10 - Base 10 logarithm of an expression.
ln - Natural logarithm of an expression.
exp - Exponential function of an expression (e^x).
geo distance - Haversine distance between two geographic points. Values need to be { "lat": 0.0, "lon": 0.0 } objects.
decay - Apply a decay function to an expression, which clamps the output between 0 and 1. Available decay functions are linear, exponential, and gaussian. See more.
datetime - Parse a datetime string (see formats here), and use it as a POSIX timestamp, in seconds.
datetime key - Specify that a payload key contains a datetime string to be parsed into POSIX seconds.
It is possible to define a default for when the variable (either from payload or prefetch score) is not found. This is given in the form of a mapping from variable to value. If there is no variable, and no defined default, a default value of 0.0 is used.

Considerations when using formula queries:

Formula queries can only be used as a rescoring step.
Formula results are always sorted in descending order (bigger is better). For euclidean scores, make sure to negate them to sort closest to farthest.
If a score or variable is not available, and there is no default value, it will return an error.
If a value is not a number (or the expected type), it will return an error.
To leverage payload indices, single-value arrays are considered the same as the inner value. For example: [0.2] is the same as 0.2, but [0.2, 0.7] will be interpreted as [0.2, 0.7]
Multiplication and division are lazily evaluated, meaning that if a 0 is encountered, the rest of operations don’t execute (e.g. 0.0 * condition won’t check the condition).
Payload variables used within the formula also benefit from having payload indices. Please try to always have a payload index set up for the variables used in the formula for better performance.
Boost points closer to user
Another example. Combine the score with how close the result is to a user.

Considering each point has an associated geo location, we can calculate the distance between the point and the request’s location.

Assuming we have cosine scores in the prefetch, we can use a helper function to clamp the geographical distance between 0 and 1, by using a decay function. Once clamped, we can sum the score and the distance together. Pseudocode:

score = score + gauss_decay(distance)

In this case we use a gauss_decay function.

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

geo_boosted = client.query_points(
    collection_name="{collection_name}",
    prefetch=models.Prefetch(
        query=[0.1, 0.45, 0.67],  # <-- dense vector
        limit=50
    ),
    query=models.FormulaQuery(
        formula=models.SumExpression(sum=[
            "$score",
            models.GaussDecayExpression(
                gauss_decay=models.DecayParamsExpression(
                    x=models.GeoDistance(
                        geo_distance=models.GeoDistanceParams(
                            origin=models.GeoPoint(
                                lat=52.504043,
                                lon=13.393236
                            ),  # Berlin
                            to="geo.location"
                        )
                    ),
                    scale=5000  # 5km
                )
            )
        ]),
        defaults={"geo.location": models.GeoPoint(lat=48.137154, lon=11.576124)}  # Munich
    )
)

Time-based score boosting
Or combine the score with the information on how “fresh” the result is. It’s applicable to (news) articles and in general many other different types of searches (think of the “newest” filter you use in applications).

To implement time-based score boosting, you’ll need each point to have a datetime field in its payload, e.g., when the item was uploaded or last updated. Then we can calculate the time difference in seconds between this payload value and the current time, our target.

With an exponential decay function, perfect for use cases with time, as freshness is a very quickly lost quality, we can convert this time difference into a value between 0 and 1, then add it to the original score to prioritise fresh results.

score = score + exp_decay(current_time - point_time)

That’s how it will look for an application where, after 1 day, results start being only half-relevant (so get a score of 0.5):

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

time_boosted = client.query_points(
    collection_name="{collection_name}",
    prefetch=models.Prefetch(
        query=[0.1, 0.45, 0.67],  # <-- dense vector
        limit=50
    ),
    query=models.FormulaQuery(
        formula=models.SumExpression(
            sum=[
                "$score", # the final score = score + exp_decay(target_time - x_time)
                models.ExpDecayExpression(
                    exp_decay=models.DecayParamsExpression(
                        x=models.DatetimeKeyExpression(
                            datetime_key="upload_time" # payload key 
                        ),
                        target=models.DatetimeExpression(
                            datetime="YYYY-MM-DDT00:00:00Z" # current datetime
                        ),
                        scale=86400, # 1 day in seconds
                        midpoint=0.5 # if item's "update_time" is more than 1 day apart from current datetime, relevance score is less than 0.5
                    )
                )
            ]
        )
    )
)

For all decay functions, there are these parameters available

Parameter	Default	Description
x	N/A	The value to decay
target	0.0	The value at which the decay will be at its peak. For distances it is usually set at 0.0, but can be set to any value.
scale	1.0	The value at which the decay function will be equal to midpoint. This is in terms of x units, for example, if x is in meters, scale of 5000 means 5km. Must be a non-zero positive number
midpoint	0.5	Output is midpoint when x equals target ± scale. Must be in the range (0.0, 1.0), exclusive
Decay functions.

The formulas for each decay function are as follows:


Decay Function	Color	Range	Formula
lin_decay	green	[0, 1]	
 
exp_decay	red	(0, 1]	
 
gauss_decay	purple	(0, 1]	
 
Grouping
Available as of v1.11.0

It is possible to group results by a certain field. This is useful when you have multiple points for the same item, and you want to avoid redundancy of the same item in the results.

REST API (Schema):

http
python
typescript
rust
java
csharp
go
client.query_points_groups(
    collection_name="{collection_name}",
    # Same as in the regular query_points() API
    query=[1.1],
    # Grouping parameters
    group_by="document_id",  # Path of the field to group by
    limit=4,  # Max amount of groups
    group_size=2,  # Max amount of points per group
)

For more information on the grouping capabilities refer to the reference documentation for search with grouping and lookup.

Was this page useful?
Thumb up iconYes








Filtering
With Qdrant, you can set conditions when searching or retrieving points. For example, you can impose conditions on both the payload and the id of the point.

Setting additional conditions is important when it is impossible to express all the features of the object in the embedding. Examples include a variety of business requirements: stock availability, user location, or desired price range.

Related Content
A Complete Guide to Filtering in Vector Search	Developer advice on proper usage and advanced practices.
Filtering clauses
Qdrant allows you to combine conditions in clauses. Clauses are different logical operations, such as OR, AND, and NOT. Clauses can be recursively nested into each other so that you can reproduce an arbitrary boolean expression.

Let’s take a look at the clauses implemented in Qdrant.

Suppose we have a set of points with the following payload:

[
  { "id": 1, "city": "London", "color": "green" },
  { "id": 2, "city": "London", "color": "red" },
  { "id": 3, "city": "London", "color": "blue" },
  { "id": 4, "city": "Berlin", "color": "red" },
  { "id": 5, "city": "Moscow", "color": "green" },
  { "id": 6, "city": "Moscow", "color": "blue" }
]

Must
Example:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.scroll(
    collection_name="{collection_name}",
    scroll_filter=models.Filter(
        must=[
            models.FieldCondition(
                key="city",
                match=models.MatchValue(value="London"),
            ),
            models.FieldCondition(
                key="color",
                match=models.MatchValue(value="red"),
            ),
        ]
    ),
)

Filtered points would be:

[{ "id": 2, "city": "London", "color": "red" }]

When using must, the clause becomes true only if every condition listed inside must is satisfied. In this sense, must is equivalent to the operator AND.

Should
Example:

http
python
typescript
rust
java
csharp
go
client.scroll(
    collection_name="{collection_name}",
    scroll_filter=models.Filter(
        should=[
            models.FieldCondition(
                key="city",
                match=models.MatchValue(value="London"),
            ),
            models.FieldCondition(
                key="color",
                match=models.MatchValue(value="red"),
            ),
        ]
    ),
)

Filtered points would be:

[
  { "id": 1, "city": "London", "color": "green" },
  { "id": 2, "city": "London", "color": "red" },
  { "id": 3, "city": "London", "color": "blue" },
  { "id": 4, "city": "Berlin", "color": "red" }
]

When using should, the clause becomes true if at least one condition listed inside should is satisfied. In this sense, should is equivalent to the operator OR.

Must Not
Example:

http
python
typescript
rust
java
csharp
go
client.scroll(
    collection_name="{collection_name}",
    scroll_filter=models.Filter(
        must_not=[
            models.FieldCondition(key="city", match=models.MatchValue(value="London")),
            models.FieldCondition(key="color", match=models.MatchValue(value="red")),
        ]
    ),
)

Filtered points would be:

[
  { "id": 5, "city": "Moscow", "color": "green" },
  { "id": 6, "city": "Moscow", "color": "blue" }
]

When using must_not, the clause becomes true if none of the conditions listed inside must_not is satisfied. In this sense, must_not is equivalent to the expression (NOT A) AND (NOT B) AND (NOT C).

Clauses combination
It is also possible to use several clauses simultaneously:

http
python
typescript
rust
java
csharp
go
client.scroll(
    collection_name="{collection_name}",
    scroll_filter=models.Filter(
        must=[
            models.FieldCondition(key="city", match=models.MatchValue(value="London")),
        ],
        must_not=[
            models.FieldCondition(key="color", match=models.MatchValue(value="red")),
        ],
    ),
)

Filtered points would be:

[
  { "id": 1, "city": "London", "color": "green" },
  { "id": 3, "city": "London", "color": "blue" }
]

In this case, the conditions are combined by AND.

Also, the conditions could be recursively nested. Example:

http
python
typescript
rust
java
csharp
go
client.scroll(
    collection_name="{collection_name}",
    scroll_filter=models.Filter(
        must_not=[
            models.Filter(
                must=[
                    models.FieldCondition(
                        key="city", match=models.MatchValue(value="London")
                    ),
                    models.FieldCondition(
                        key="color", match=models.MatchValue(value="red")
                    ),
                ],
            ),
        ],
    ),
)

Filtered points would be:

[
  { "id": 1, "city": "London", "color": "green" },
  { "id": 3, "city": "London", "color": "blue" },
  { "id": 4, "city": "Berlin", "color": "red" },
  { "id": 5, "city": "Moscow", "color": "green" },
  { "id": 6, "city": "Moscow", "color": "blue" }
]

Filtering conditions
Different types of values in payload correspond to different kinds of queries that we can apply to them. Let’s look at the existing condition variants and what types of data they apply to.

Match
json
python
typescript
rust
java
csharp
go
models.FieldCondition(
    key="color",
    match=models.MatchValue(value="red"),
)

For the other types, the match condition will look exactly the same, except for the type used:

json
python
typescript
rust
java
csharp
go
models.FieldCondition(
    key="count",
    match=models.MatchValue(value=0),
)

The simplest kind of condition is one that checks if the stored value equals the given one. If several values are stored, at least one of them should match the condition. You can apply it to keyword, integer and bool payloads.

Match Any
Available as of v1.1.0

In case you want to check if the stored value is one of multiple values, you can use the Match Any condition. Match Any works as a logical OR for the given values. It can also be described as a IN operator.

You can apply it to keyword and integer payloads.

Example:

json
python
typescript
rust
java
csharp
go
models.FieldCondition(
    key="color",
    match=models.MatchAny(any=["black", "yellow"]),
)

In this example, the condition will be satisfied if the stored value is either black or yellow.

If the stored value is an array, it should have at least one value matching any of the given values. E.g. if the stored value is ["black", "green"], the condition will be satisfied, because "black" is in ["black", "yellow"].

Match Except
Available as of v1.2.0

In case you want to check if the stored value is not one of multiple values, you can use the Match Except condition. Match Except works as a logical NOR for the given values. It can also be described as a NOT IN operator.

You can apply it to keyword and integer payloads.

Example:

json
python
typescript
rust
java
csharp
go
models.FieldCondition(
    key="color",
    match=models.MatchExcept(**{"except": ["black", "yellow"]}),
)

In this example, the condition will be satisfied if the stored value is neither black nor yellow.

If the stored value is an array, it should have at least one value not matching any of the given values. E.g. if the stored value is ["black", "green"], the condition will be satisfied, because "green" does not match "black" nor "yellow".

Nested key
Available as of v1.1.0

Payloads being arbitrary JSON object, it is likely that you will need to filter on a nested field.

For convenience, we use a syntax similar to what can be found in the Jq project.

Suppose we have a set of points with the following payload:

[
  {
    "id": 1,
    "country": {
      "name": "Germany",
      "cities": [
        {
          "name": "Berlin",
          "population": 3.7,
          "sightseeing": ["Brandenburg Gate", "Reichstag"]
        },
        {
          "name": "Munich",
          "population": 1.5,
          "sightseeing": ["Marienplatz", "Olympiapark"]
        }
      ]
    }
  },
  {
    "id": 2,
    "country": {
      "name": "Japan",
      "cities": [
        {
          "name": "Tokyo",
          "population": 9.3,
          "sightseeing": ["Tokyo Tower", "Tokyo Skytree"]
        },
        {
          "name": "Osaka",
          "population": 2.7,
          "sightseeing": ["Osaka Castle", "Universal Studios Japan"]
        }
      ]
    }
  }
]

You can search on a nested field using a dot notation.

http
python
typescript
rust
java
csharp
go
client.scroll(
    collection_name="{collection_name}",
    scroll_filter=models.Filter(
        should=[
            models.FieldCondition(
                key="country.name", match=models.MatchValue(value="Germany")
            ),
        ],
    ),
)

You can also search through arrays by projecting inner values using the [] syntax.

http
python
typescript
rust
java
csharp
go
client.scroll(
    collection_name="{collection_name}",
    scroll_filter=models.Filter(
        should=[
            models.FieldCondition(
                key="country.cities[].population",
                range=models.Range(
                    gt=None,
                    gte=9.0,
                    lt=None,
                    lte=None,
                ),
            ),
        ],
    ),
)

This query would only output the point with id 2 as only Japan has a city with population greater than 9.0.

And the leaf nested field can also be an array.

http
python
typescript
rust
java
csharp
go
client.scroll(
    collection_name="{collection_name}",
    scroll_filter=models.Filter(
        should=[
            models.FieldCondition(
                key="country.cities[].sightseeing",
                match=models.MatchValue(value="Osaka Castle"),
            ),
        ],
    ),
)

This query would only output the point with id 2 as only Japan has a city with the “Osaka castke” as part of the sightseeing.

Nested object filter
Available as of v1.2.0

By default, the conditions are taking into account the entire payload of a point.

For instance, given two points with the following payload:

[
  {
    "id": 1,
    "dinosaur": "t-rex",
    "diet": [
      { "food": "leaves", "likes": false},
      { "food": "meat", "likes": true}
    ]
  },
  {
    "id": 2,
    "dinosaur": "diplodocus",
    "diet": [
      { "food": "leaves", "likes": true},
      { "food": "meat", "likes": false}
    ]
  }
]

The following query would match both points:

http
python
typescript
rust
java
csharp
go
client.scroll(
    collection_name="{collection_name}",
    scroll_filter=models.Filter(
        must=[
            models.FieldCondition(
                key="diet[].food", match=models.MatchValue(value="meat")
            ),
            models.FieldCondition(
                key="diet[].likes", match=models.MatchValue(value=True)
            ),
        ],
    ),
)

This happens because both points are matching the two conditions:

the “t-rex” matches food=meat on diet[1].food and likes=true on diet[1].likes
the “diplodocus” matches food=meat on diet[1].food and likes=true on diet[0].likes
To retrieve only the points which are matching the conditions on an array element basis, that is the point with id 1 in this example, you would need to use a nested object filter.

Nested object filters allow arrays of objects to be queried independently of each other.

It is achieved by using the nested condition type formed by a payload key to focus on and a filter to apply.

The key should point to an array of objects and can be used with or without the bracket notation (“data” or “data[]”).

http
python
typescript
rust
java
csharp
go
client.scroll(
    collection_name="{collection_name}",
    scroll_filter=models.Filter(
        must=[
            models.NestedCondition(
                nested=models.Nested(
                    key="diet",
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="food", match=models.MatchValue(value="meat")
                            ),
                            models.FieldCondition(
                                key="likes", match=models.MatchValue(value=True)
                            ),
                        ]
                    ),
                )
            )
        ],
    ),
)

The matching logic is modified to be applied at the level of an array element within the payload.

Nested filters work in the same way as if the nested filter was applied to a single element of the array at a time. Parent document is considered to match the condition if at least one element of the array matches the nested filter.

Limitations

The has_id condition is not supported within the nested object filter. If you need it, place it in an adjacent must clause.

http
python
typescript
rust
java
csharp
go
client.scroll(
    collection_name="{collection_name}",
    scroll_filter=models.Filter(
        must=[
            models.NestedCondition(
                nested=models.Nested(
                    key="diet",
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="food", match=models.MatchValue(value="meat")
                            ),
                            models.FieldCondition(
                                key="likes", match=models.MatchValue(value=True)
                            ),
                        ]
                    ),
                )
            ),
            models.HasIdCondition(has_id=[1]),
        ],
    ),
)

Full Text Match
Available as of v0.10.0

A special case of the match condition is the text match condition. It allows you to search for a specific substring, token or phrase within the text field.

Exact texts that will match the condition depend on full-text index configuration. Configuration is defined during the index creation and describe at full-text index.

If there is no full-text index for the field, the condition will work as exact substring match.

json
python
typescript
rust
java
csharp
go
models.FieldCondition(
    key="description",
    match=models.MatchText(text="good cheap"),
)

If the query has several words, then the condition will be satisfied only if all of them are present in the text.

Full Text Any
Available as of v1.16.0

The text_any full-text match condition is similar to the text condition, but with a key difference: while text only matches text fields that contain all the query terms, text_any matches fields that contain any of the query terms. In other words, even if a text field contains just one of the query terms, it is considered a match.

For example, a query for good cheap matches cheap hardware as well as good performance.

json
python
typescript
rust
java
csharp
go
models.FieldCondition(
    key="description",
    match=models.MatchTextAny(text_any="good cheap"),
)

Phrase Match
Available as of v1.15.0

A match phrase condition also leverages full-text index, to perform exact phrase comparisons. It allows you to search for a specific token phrase within the text field.

For example, the text "quick brown fox" will be matched by the query "brown fox", but not by "fox brown".

The index must be configured with phrase_matching parameter set to true. If the index has phrase matching disabled, phrase conditions won't match anything.
If there is no full-text index for the field, the condition will work as exact substring match.

json
python
typescript
rust
java
csharp
go
models.FieldCondition(
    key="description",
    match=models.MatchPhrase(phrase="brown fox"),
)

Range
json
python
typescript
rust
java
csharp
go
models.FieldCondition(
    key="price",
    range=models.Range(
        gt=None,
        gte=100.0,
        lt=None,
        lte=450.0,
    ),
)

The range condition sets the range of possible values for stored payload values. If several values are stored, at least one of them should match the condition.

Comparisons that can be used:

gt - greater than
gte - greater than or equal
lt - less than
lte - less than or equal
Can be applied to float and integer payloads.

Datetime Range
The datetime range is a unique range condition, used for datetime payloads, which supports RFC 3339 formats. You do not need to convert dates to UNIX timestaps. During comparison, timestamps are parsed and converted to UTC.

Available as of v1.8.0

json
python
typescript
rust
java
csharp
go
models.FieldCondition(
    key="date",
    range=models.DatetimeRange(
        gt="2023-02-08T10:49:00Z",
        gte=None,
        lt=None,
        lte="2024-01-31T10:14:31Z",
    ),
)

UUID Match
Available as of v1.11.0

Matching of UUID values works similarly to the regular match condition for strings. Functionally, it will work with keyword and uuid indexes exactly the same, but uuid index is more memory efficient.

json
python
typescript
rust
java
csharp
go
models.FieldCondition(
    key="uuid",
    match=models.MatchValue(value="f47ac10b-58cc-4372-a567-0e02b2c3d479"),
)

Geo
Geo Bounding Box
json
python
typescript
rust
java
csharp
go
models.FieldCondition(
    key="location",
    geo_bounding_box=models.GeoBoundingBox(
        bottom_right=models.GeoPoint(
            lon=13.455868,
            lat=52.495862,
        ),
        top_left=models.GeoPoint(
            lon=13.403683,
            lat=52.520711,
        ),
    ),
)

It matches with locations inside a rectangle with the coordinates of the upper left corner in top_left and the coordinates of the lower right corner in bottom_right.

Geo Radius
json
python
typescript
rust
java
csharp
go
models.FieldCondition(
    key="location",
    geo_radius=models.GeoRadius(
        center=models.GeoPoint(
            lon=13.403683,
            lat=52.520711,
        ),
        radius=1000.0,
    ),
)

It matches with locations inside a circle with the center at the center and a radius of radius meters.

If several values are stored, at least one of them should match the condition. These conditions can only be applied to payloads that match the geo-data format.

Geo Polygon
Geo Polygons search is useful for when you want to find points inside an irregularly shaped area, for example a country boundary or a forest boundary. A polygon always has an exterior ring and may optionally include interior rings. A lake with an island would be an example of an interior ring. If you wanted to find points in the water but not on the island, you would make an interior ring for the island.

When defining a ring, you must pick either a clockwise or counterclockwise ordering for your points. The first and last point of the polygon must be the same.

Currently, we only support unprojected global coordinates (decimal degrees longitude and latitude) and we are datum agnostic.

json
python
typescript
rust
java
csharp
go
models.FieldCondition(
    key="location",
    geo_polygon=models.GeoPolygon(
        exterior=models.GeoLineString(
            points=[
                models.GeoPoint(
                    lon=-70.0,
                    lat=-70.0,
                ),
                models.GeoPoint(
                    lon=60.0,
                    lat=-70.0,
                ),
                models.GeoPoint(
                    lon=60.0,
                    lat=60.0,
                ),
                models.GeoPoint(
                    lon=-70.0,
                    lat=60.0,
                ),
                models.GeoPoint(
                    lon=-70.0,
                    lat=-70.0,
                ),
            ]
        ),
        interiors=[
            models.GeoLineString(
                points=[
                    models.GeoPoint(
                        lon=-65.0,
                        lat=-65.0,
                    ),
                    models.GeoPoint(
                        lon=0.0,
                        lat=-65.0,
                    ),
                    models.GeoPoint(
                        lon=0.0,
                        lat=0.0,
                    ),
                    models.GeoPoint(
                        lon=-65.0,
                        lat=0.0,
                    ),
                    models.GeoPoint(
                        lon=-65.0,
                        lat=-65.0,
                    ),
                ]
            )
        ],
    ),
)

A match is considered any point location inside or on the boundaries of the given polygon’s exterior but not inside any interiors.

If several location values are stored for a point, then any of them matching will include that point as a candidate in the resultset. These conditions can only be applied to payloads that match the geo-data format.

Values count
In addition to the direct value comparison, it is also possible to filter by the amount of values.

For example, given the data:

[
  { "id": 1, "name": "product A", "comments": ["Very good!", "Excellent"] },
  { "id": 2, "name": "product B", "comments": ["meh", "expected more", "ok"] }
]

We can perform the search only among the items with more than two comments:

json
python
typescript
rust
java
csharp
go
models.FieldCondition(
    key="comments",
    values_count=models.ValuesCount(gt=2),
)

The result would be:

[{ "id": 2, "name": "product B", "comments": ["meh", "expected more", "ok"] }]

If stored value is not an array - it is assumed that the amount of values is equals to 1.

Is Empty
Sometimes it is also useful to filter out records that are missing some value. The IsEmpty condition may help you with that:

json
python
typescript
rust
java
csharp
go
models.IsEmptyCondition(
    is_empty=models.PayloadField(key="reports"),
)

This condition will match all records where the field reports either does not exist, or has null or [] value.

The IsEmpty is often useful together with the logical negation must_not. In this case all non-empty values will be selected.
Is Null
It is not possible to test for NULL values with the match condition. We have to use IsNull condition instead:

json
python
typescript
rust
java
csharp
go
models.IsNullCondition(
    is_null=models.PayloadField(key="reports"),
)

This condition will match all records where the field reports exists and has NULL value.

Has id
This type of query is not related to payload, but can be very useful in some situations. For example, the user could mark some specific search results as irrelevant, or we want to search only among the specified points.

http
python
typescript
rust
java
csharp
go
client.scroll(
    collection_name="{collection_name}",
    scroll_filter=models.Filter(
        must=[
            models.HasIdCondition(has_id=[1, 3, 5, 7, 9, 11]),
        ],
    ),
)

Filtered points would be:

[
  { "id": 1, "city": "London", "color": "green" },
  { "id": 3, "city": "London", "color": "blue" },
  { "id": 5, "city": "Moscow", "color": "green" }
]

Has vector
Available as of v1.13.0

This condition enables filtering by the presence of a given named vector on a point.

For example, if we have two named vector in our collection.

PUT /collections/{collection_name}
{
    "vectors": {
        "image": {
            "size": 4,
            "distance": "Dot"
        },
        "text": {
            "size": 8,
            "distance": "Cosine"
        }
    },
    "sparse_vectors": {
        "sparse-image": {},
        "sparse-text": {},
    },
}

Some points in the collection might have all vectors, some might have only a subset of them.

If your collection does not have named vectors, use an empty ("") name.
This is how you can search for points which have the dense image vector defined:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.scroll(
    collection_name="{collection_name}",
    scroll_filter=models.Filter(
        must=[
            models.HasVectorCondition(has_vector="image"),
        ],
    ),
)








Inference
Inference is the process of using a machine learning model to create vector embeddings from text, images, or other data types. While you can create embeddings on the client side, you can also let Qdrant generate them while storing or querying data.

Inference

There are several advantages to generating embeddings with Qdrant:

No need for external pipelines or separate model servers.
Work with a single unified API instead of a different API per model provider.
No external network calls, minimizing delays or data transfer overhead.
Depending on the model you want to use, inference can be executed:

on the client side, using the FastEmbed library
by the Qdrant cluster (only supported for the BM25 model)
in Qdrant Cloud, using Cloud Inference (for clusters on Qdrant Managed Cloud)
externally (models by OpenAI, Cohere, and Jina AI; for clusters on Qdrant Managed Cloud)
Inference API
You can use inference in the API wherever you can use regular vectors. Instead of a vector, you can use special Inference Objects:

Document object, used for text inference

// Document
{
    // Text input
    text: "Your text",
    // Name of the model, to do inference with
    model: "<the-model-to-use>",
    // Extra parameters for the model, Optional
    options: {}
}

Image object, used for image inference

// Image
{
    // Image input
    image: "<url>", // Or base64 encoded image
    // Name of the model, to do inference with
    model: "<the-model-to-use>",
    // Extra parameters for the model, Optional
    options: {}
}

Object object, reserved for other types of input, which might be implemented in the future.

The Qdrant API supports the usage of these Inference Objects in all places where regular vectors can be used. For example:

POST /collections/<your-collection>/points/query
{
  "query": {
    "nearest": [0.12, 0.34, 0.56, 0.78, ...]
  }
}

Can be replaced with

POST /collections/<your-collection>/points/query
{
  "query": {
    "nearest": {
      "text": "My Query Text",
      "model": "<the-model-to-use>"
    }
  }
}

In this case, Qdrant uses the configured embedding model to automatically create a vector from the Inference Object and then perform the search query with it. All of this happens within a low-latency network.

When using inference at ingest time, the input used for inference is not stored. If you want to persist it in Qdrant, ensure that you explicitly include it in the payload.
Server-side Inference: BM25
BM25 (Best Matching 25) is a ranking function for text search. BM25 uses sparse vectors that represent documents, where each dimension corresponds to a word. Qdrant can generate these sparse embeddings from input text directly on the server.

While upserting points, provide the text and the qdrant/bm25 embedding model:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(
    url="https://xyz-example.qdrant.io:6333", 
    api_key="<your-api-key>", 
    cloud_inference=True
)

client.upsert(
    collection_name="{collection_name}",
    points=[
        models.PointStruct(
            id=1,
            vector={
                "my-bm25-vector": models.Document(
                    text="Recipe for baking chocolate chip cookies",
                    model="Qdrant/bm25",
                )
            },
        )
    ],
)

Qdrant uses the model to generate the embeddings and stores the point with the resulting vector. Retrieving the point shows the embeddings that were generated:

    ....
      "my-bm25-vector": {
        "indices": [
          112174620,
          177304315,
          662344706,
          771857363,
          1617337648
        ],
        "values": [
          1.6697302,
          1.6697302,
          1.6697302,
          1.6697302,
          1.6697302
        ]
      }
    ....
]

Similarly, you can use inference at query time by providing the text to query with as well as the embedding model:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(
    url="https://xyz-example.qdrant.io:6333", 
    api_key="<your-api-key>", 
    cloud_inference=True
)

client.query_points(
    collection_name="{collection_name}",
    query=models.Document(
        text="How to bake cookies?", 
        model="Qdrant/bm25",
    ),
    using="my-bm25-vector",
)

Qdrant Cloud Inference
Clusters on Qdrant Managed Cloud can access embedding models that are hosted on Qdrant Cloud. For a list of available models, visit the Inference tab of the Cluster Detail page in the Qdrant Cloud Console. Here, you can also enable Cloud Inference for a cluster if it’s not already enabled.

Before using a Cloud-hosted embedding model, ensure that your collection has been configured for vectors with the correct dimensionality. The Inference tab of the Cluster Detail page in the Qdrant Cloud Console lists the dimensionality for each supported embedding model.

Text Inference
Let’s consider an example of using Cloud Inference with a text model that produces dense vectors. This example creates one point and uses a simple search query with a Document Inference Object.

http
bash
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Document

client = QdrantClient(
    url="https://xyz-example.qdrant.io:6333",
    api_key="<paste-your-api-key-here>",
    # IMPORTANT
    # If not enabled, inference will be performed locally
    cloud_inference=True,
)

points = [
    PointStruct(
        id=1,
        payload={"topic": "cooking", "type": "dessert"},
        vector=Document(
            text="Recipe for baking chocolate chip cookies",
            model="<the-model-to-use>"
        )
    )
]

client.upsert(collection_name="<your-collection>", points=points)

result = client.query_points(
    collection_name="<your-collection>",
    query=Document(
        text="How to bake cookies?",
        model="<the-model-to-use>"
    )
)

print(result)

Usage examples, specific to each cluster and model, can also be found in the Inference tab of the Cluster Detail page in the Qdrant Cloud Console.

Note that each model has a context window, which is the maximum number of tokens that can be processed by the model in a single request. If the input text exceeds the context window, it is truncated to fit within the limit. The context window size is displayed in the Inference tab of the Cluster Detail page.

For dense vector models, you also have to ensure that the vector size configured in the collection matches the output size of the model. If the vector size does not match, the upsert will fail with an error.

Image Inference
Here is another example of using Cloud Inference with an image model. This example uses the CLIP model to encode an image and then uses a text query to search for it.

Since the CLIP model is multimodal, we can use both image and text inputs on the same vector field.

http
bash
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Image, Document

client = QdrantClient(
    url="https://xyz-example.qdrant.io:6333",
    api_key="<paste-your-api-key-here>",
    # IMPORTANT
    # If not enabled, inference will be performed locally
    cloud_inference=True,
)

points = [
    PointStruct(
        id=1,
        vector=Image(
            image="https://qdrant.tech/example.png",
            model="qdrant/clip-vit-b-32-vision"
        ),
        payload={
            "title": "Example Image"
        }
    )
]

client.upsert(collection_name="<your-collection>", points=points)

result = client.query_points(
    collection_name="<your-collection>",
    query=Document(
        text="Mission to Mars",
        model="qdrant/clip-vit-b-32-text"
    )
)

print(result)

The Qdrant Cloud Inference server will download the images using the provided URL. Alternatively, you can provide the image as a base64-encoded string. Each model has limitations on the file size and extensions it can work with. Refer to the model card for details.

Local Inference Compatibility
The Python SDK offers a unique capability: it supports both local and cloud inference through an identical interface.

You can easily switch between local and cloud inference by setting the cloud_inference flag when initializing the QdrantClient. For example:

client = QdrantClient(
    url="https://your-cluster.qdrant.io",
    api_key="<your-api-key>",
    cloud_inference=True,  # Set to False to use local inference
)

This flexibility allows you to develop and test your applications locally or in continuous integration (CI) environments without requiring access to cloud inference resources.

When cloud_inference is set to False, inference is performed locally using fastembed.
When set to True, inference requests are handled by Qdrant Cloud.
External Embedding Model Providers
Qdrant Cloud can act as a proxy for the APIs of external embedding model providers:

OpenAI
Cohere
Jina AI
OpenRouter
This enables you to access any of the embedding models provided by these providers through the Qdrant API.

Inference with an external embedding model provider

To use an external provider’s embedding model, you need an API key from that provider. For example, to access OpenAI models, you need an OpenAI API key. Qdrant does not store or cache your API keys; they must be provided with each inference request.

When using an external embedding model, ensure that your collection has been configured for vectors with the correct dimensionality. Refer to the model’s documentation for details on the output dimensions.

When using a model from an external provider, refer to the model's documentation for:
the dimensions of the resulting embeddings
how to pass an image when creating image embeddings. Some providers allow you to pass an image URL, while others require a base64-encoded image
any additional parameters that the model supports
OpenAI
When you prepend a model name with openai/, the embedding request is automatically routed to the OpenAI Embeddings API.

For example, to use OpenAI’s text-embedding-3-large model when ingesting data, prepend the model name with openai/ and provide your OpenAI API key in the options object. Any OpenAI-specific API parameters can be passed using the options object. This example uses the OpenAI-specific API dimensions parameter to reduce the dimensionality to 512:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(
    url="https://xyz-example.qdrant.io:6333", 
    api_key="<your-api-key>", 
    cloud_inference=True
)

client.upsert(
    collection_name="{collection_name}",
    points=[
        models.PointStruct(
            id=1,
            vector=models.Document(
                text="Recipe for baking chocolate chip cookies",
                model="openai/text-embedding-3-large",
                options={
                    "openai-api-key": "<your_openai_api_key>",
                    "dimensions": 512
                }
            )
        )
    ]
)

At query time, you can use the same model by prepending the model name with openai/ and providing your OpenAI API key in the options object. This example again uses the OpenAI-specific API dimensions parameter to reduce the dimensionality to 512:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(
    url="https://xyz-example.qdrant.io:6333",
    api_key="<your-api-key>",
    cloud_inference=True
)

client.query_points(
    collection_name="{collection_name}",
    query=models.Document(
        text="How to bake cookies?",
        model="openai/text-embedding-3-large",
        options={
            "openai-api-key": "<your_openai_api_key>",
            "dimensions": 512
        }
    )
)

Note that, because Qdrant does not store or cache your OpenAI API key, you need to provide it with each inference request.Optimizer
It is much more efficient to apply changes in batches than perform each change individually, as many other databases do. Qdrant here is no exception. Since Qdrant operates with data structures that are not always easy to change, it is sometimes necessary to rebuild those structures completely.

Storage optimization in Qdrant occurs at the segment level (see storage). In this case, the segment to be optimized remains readable for the time of the rebuild.

Segment optimization

The availability is achieved by wrapping the segment into a proxy that transparently handles data changes. Changed data is placed in the copy-on-write segment, which has priority for retrieval and subsequent updates.

Vacuum Optimizer
The simplest example of a case where you need to rebuild a segment repository is to remove points. Like many other databases, Qdrant does not delete entries immediately after a query. Instead, it marks records as deleted and ignores them for future queries.

This strategy allows us to minimize disk access - one of the slowest operations. However, a side effect of this strategy is that, over time, deleted records accumulate, occupy memory and slow down the system.

To avoid these adverse effects, Vacuum Optimizer is used. It is used if the segment has accumulated too many deleted records.

The criteria for starting the optimizer are defined in the configuration file.

Here is an example of parameter values:

storage:
  optimizers:
    # The minimal fraction of deleted vectors in a segment, required to perform segment optimization
    deleted_threshold: 0.2
    # The minimal number of vectors in a segment, required to perform segment optimization
    vacuum_min_vector_number: 1000

Merge Optimizer
The service may require the creation of temporary segments. Such segments, for example, are created as copy-on-write segments during optimization itself.

It is also essential to have at least one small segment that Qdrant will use to store frequently updated data. On the other hand, too many small segments lead to suboptimal search performance.

The merge optimizer constantly tries to reduce the number of segments if there currently are too many. The desired number of segments is specified with default_segment_number and defaults to the number of CPUs. The optimizer may takes at least the three smallest segments and merges them into one.

Segments will not be merged if they’ll exceed the maximum configured segment size with max_segment_size_kb. It prevents creating segments that are too large to efficiently index. Increasing this number may help to reduce the number of segments if you have a lot of data, and can potentially improve search performance.

The criteria for starting the optimizer are defined in the configuration file.

Here is an example of parameter values:

storage:
  optimizers:
    # Target amount of segments optimizer will try to keep.
    # Real amount of segments may vary depending on multiple parameters:
    #  - Amount of stored points
    #  - Current write RPS
    #
    # It is recommended to select default number of segments as a factor of the number of search threads,
    # so that each segment would be handled evenly by one of the threads.
    # If `default_segment_number = 0`, will be automatically selected by the number of available CPUs
    default_segment_number: 0

    # Do not create segments larger this size (in KiloBytes).
    # Large segments might require disproportionately long indexation times,
    # therefore it makes sense to limit the size of segments.
    #
    # If indexation speed have more priority for your - make this parameter lower.
    # If search speed is more important - make this parameter higher.
    # Note: 1Kb = 1 vector of size 256
    # If not set, will be automatically selected considering the number of available CPUs.
    max_segment_size_kb: null

Indexing Optimizer
Qdrant allows you to choose the type of indexes and data storage methods used depending on the number of records. So, for example, if the number of points is less than 10000, using any index would be less efficient than a brute force scan.

The Indexing Optimizer is used to implement the enabling of indexes and memmap storage when the minimal amount of records is reached.

The criteria for starting the optimizer are defined in the configuration file.

Here is an example of parameter values:

storage:
  optimizers:
    # Maximum size (in kilobytes) of vectors to store in-memory per segment.
    # Segments larger than this threshold will be stored as read-only memmaped file.
    # Memmap storage is disabled by default, to enable it, set this threshold to a reasonable value.
    # To disable memmap storage, set this to `0`.
    # Note: 1Kb = 1 vector of size 256
    memmap_threshold: 200000

    # Maximum size (in kilobytes) of vectors allowed for plain index, exceeding this threshold will enable vector indexing
    # Default value is 20,000, based on <https://github.com/google-research/google-research/blob/master/scann/docs/algorithms.md>.
    # To disable vector indexing, set to `0`.
    # Note: 1kB = 1 vector of size 256.
    indexing_threshold_kb: 20000

In addition to the configuration file, you can also set optimizer parameters separately for each collection.

Dynamic parameter updates may be useful, for example, for more efficient initial loading of points. You can disable indexing during the upload process with these settings and enable it immediately after it is finished. As a result, you will not waste extra computation resources on rebuilding the index.Storage
All data within one collection is divided into segments. Each segment has its independent vector and payload storage as well as indexes.

Data stored in segments usually do not overlap. However, storing the same point in different segments will not cause problems since the search contains a deduplication mechanism.

The segments consist of vector and payload storages, vector and payload indexes, and id mapper, which stores the relationship between internal and external ids.

A segment can be appendable or non-appendable depending on the type of storage and index used. You can freely add, delete and query data in the appendable segment. With non-appendable segment can only read and delete data.

The configuration of the segments in the collection can be different and independent of one another, but at least one `appendable’ segment must be present in a collection.

Vector storage
Depending on the requirements of the application, Qdrant can use one of the data storage options. The choice has to be made between the search speed and the size of the RAM used.

In-memory storage - Stores all vectors in RAM, has the highest speed since disk access is required only for persistence.

Memmap storage - Creates a virtual address space associated with the file on disk. Wiki. Mmapped files are not directly loaded into RAM. Instead, they use page cache to access the contents of the file. This scheme allows flexible use of available memory. With sufficient RAM, it is almost as fast as in-memory storage.

Configuring Memmap storage
There are two ways to configure the usage of memmap(also known as on-disk) storage:

Set up on_disk option for the vectors in the collection create API:
Available as of v1.2.0

http
python
typescript
rust
java
csharp
go
PUT /collections/{collection_name}
{
    "vectors": {
      "size": 768,
      "distance": "Cosine",
      "on_disk": true
    }
}

This will create a collection with all vectors immediately stored in memmap storage. This is the recommended way, in case your Qdrant instance operates with fast disks and you are working with large collections.

Set up memmap_threshold option. This option will set the threshold after which the segment will be converted to memmap storage.
There are two ways to do this:

You can set the threshold globally in the configuration file. The parameter is called memmap_threshold (previously memmap_threshold_kb).
You can set the threshold for each collection separately during creation or update.
http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.create_collection(
    collection_name="{collection_name}",
    vectors_config=models.VectorParams(size=768, distance=models.Distance.COSINE),
    optimizers_config=models.OptimizersConfigDiff(indexing_threshold=20000),
)

The rule of thumb to set the memmap threshold parameter is simple:

if you have a balanced use scenario - set memmap threshold the same as indexing_threshold (default is 20000). In this case the optimizer will not make any extra runs and will optimize all thresholds at once.
if you have a high write load and low RAM - set memmap threshold lower than indexing_threshold to e.g. 10000. In this case the optimizer will convert the segments to memmap storage first and will only apply indexing after that.
In addition, you can use memmap storage not only for vectors, but also for HNSW index. To enable this, you need to set the hnsw_config.on_disk parameter to true during collection creation or updating.

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.create_collection(
    collection_name="{collection_name}",
    vectors_config=models.VectorParams(size=768, distance=models.Distance.COSINE, on_disk=True),
    hnsw_config=models.HnswConfigDiff(on_disk=True),
)

Payload storage
Qdrant supports two types of payload storages: InMemory and OnDisk.

InMemory payload storage is organized in the same way as in-memory vectors. The payload data is loaded into RAM at service startup while disk and Gridstore are used for persistence only. This type of storage works quite fast, but it may require a lot of space to keep all the data in RAM, especially if the payload has large values attached - abstracts of text or even images.

In the case of large payload values, it might be better to use OnDisk payload storage. This type of storage will read and write payload directly to RocksDB, so it won’t require any significant amount of RAM to store. The downside, however, is the access latency. If you need to query vectors with some payload-based conditions - checking values stored on disk might take too much time. In this scenario, we recommend creating a payload index for each field used in filtering conditions to avoid disk access. Once you create the field index, Qdrant will preserve all values of the indexed field in RAM regardless of the payload storage type.

You can specify the desired type of payload storage with configuration file or with collection parameter on_disk_payload during creation of the collection.

Versioning
To ensure data integrity, Qdrant performs all data changes in 2 stages. In the first step, the data is written to the Write-ahead-log(WAL), which orders all operations and assigns them a sequential number.

Once a change has been added to the WAL, it will not be lost even if a power loss occurs. Then the changes go into the segments. Each segment stores the last version of the change applied to it as well as the version of each individual point. If the new change has a sequential number less than the current version of the point, the updater will ignore the change. This mechanism allows Qdrant to safely and efficiently restore the storage from the WAL in case of an abnormal shutdown.







Indexing
A key feature of Qdrant is the effective combination of vector and traditional indexes. It is essential to have this because for vector search to work effectively with filters, having a vector index only is not enough. In simpler terms, a vector index speeds up vector search, and payload indexes speed up filtering.

The indexes in the segments exist independently, but the parameters of the indexes themselves are configured for the whole collection.

Not all segments automatically have indexes. Their necessity is determined by the optimizer settings and depends, as a rule, on the number of stored points.

Payload Index
Payload index in Qdrant is similar to the index in conventional document-oriented databases. This index is built for a specific field and type, and is used for quick point requests by the corresponding filtering condition.

The index is also used to accurately estimate the filter cardinality, which helps the query planning choose a search strategy.

Creating an index requires additional computational resources and memory, so choosing fields to be indexed is essential. Qdrant does not make this choice but grants it to the user.

To mark a field as indexable, you can use the following:

http
python
typescript
rust
java
csharp
go
client.create_payload_index(
    collection_name="{collection_name}",
    field_name="name_of_the_field_to_index",
    field_schema="keyword",
)

You can use dot notation to specify a nested field for indexing. Similar to specifying nested filters.

Available field types are:

keyword - for keyword payload, affects Match filtering conditions.
integer - for integer payload, affects Match and Range filtering conditions.
float - for float payload, affects Range filtering conditions.
bool - for bool payload, affects Match filtering conditions (available as of v1.4.0).
geo - for geo payload, affects Geo Bounding Box and Geo Radius filtering conditions.
datetime - for datetime payload, affects Range filtering conditions (available as of v1.8.0).
text - a special kind of index, available for keyword / string payloads, affects Full Text search filtering conditions. Read more about text index configuration
uuid - a special type of index, similar to keyword, but optimized for UUID values. Affects Match filtering conditions. (available as of v1.11.0)
Payload index may occupy some additional memory, so it is recommended to only use the index for those fields that are used in filtering conditions. If you need to filter by many fields and the memory limits do not allow for indexing all of them, it is recommended to choose the field that limits the search result the most. As a rule, the more different values a payload value has, the more efficiently the index will be used.

It's highly recommended to create all payload indices immediately after collection creation. Creating them later may block updates for some time. HNSW graphs will also only benefit from additional optimizations (extra edges) when they are generated after payload index creation.
Parameterized index
Available as of v1.8.0

We’ve added a parameterized variant to the integer index, which allows you to fine-tune indexing and search performance.

Both the regular and parameterized integer indexes use the following flags:

lookup: enables support for direct lookup using Match filters.
range: enables support for Range filters.
The regular integer index assumes both lookup and range are true. In contrast, to configure a parameterized index, you would set only one of these filters to true:

lookup	range	Result
true	true	Regular integer index
true	false	Parameterized integer index
false	true	Parameterized integer index
false	false	No integer index
The parameterized index can enhance performance in collections with millions of points. We encourage you to try it out. If it does not enhance performance in your use case, you can always restore the regular integer index.

Note: If you set "lookup": true with a range filter, that may lead to significant performance issues.

For example, the following code sets up a parameterized integer index which supports only range filters:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.create_payload_index(
    collection_name="{collection_name}",
    field_name="name_of_the_field_to_index",
    field_schema=models.IntegerIndexParams(
        type=models.IntegerIndexType.INTEGER,
        lookup=False,
        range=True,
    ),
)

On-disk payload index
Available as of v1.11.0

By default all payload-related structures are stored in memory. In this way, the vector index can quickly access payload values during search. As latency in this case is critical, it is recommended to keep hot payload indexes in memory.

There are, however, cases when payload indexes are too large or rarely used. In those cases, it is possible to store payload indexes on disk.

On-disk payload index might affect cold requests latency, as it requires additional disk I/O operations.
To configure on-disk payload index, you can use the following index parameters:

http
python
typescript
rust
java
csharp
go
client.create_payload_index(
    collection_name="{collection_name}",
    field_name="payload_field_name",
    field_schema=models.KeywordIndexParams(
        type=models.KeywordIndexType.KEYWORD,
        on_disk=True,
    ),
)

Payload index on-disk is supported for the following types:

keyword
integer
float
datetime
uuid
text
geo
The list will be extended in future versions.

Tenant Index
Available as of v1.11.0

Many vector search use-cases require multitenancy. In a multi-tenant scenario the collection is expected to contain multiple subsets of data, where each subset belongs to a different tenant.

Qdrant supports efficient multi-tenant search by enabling special configuration vector index, which disables global search and only builds sub-indexes for each tenant.

In Qdrant, tenants are not necessarily non-overlapping. It is possible to have subsets of data that belong to multiple tenants.
However, knowing that the collection contains multiple tenants unlocks more opportunities for optimization. To optimize storage in Qdrant further, you can enable tenant indexing for payload fields.

This option will tell Qdrant which fields are used for tenant identification and will allow Qdrant to structure storage for faster search of tenant-specific data. One example of such optimization is localizing tenant-specific data closer on disk, which will reduce the number of disk reads during search.

To enable tenant index for a field, you can use the following index parameters:

http
python
typescript
rust
java
csharp
go
client.create_payload_index(
    collection_name="{collection_name}",
    field_name="payload_field_name",
    field_schema=models.KeywordIndexParams(
        type=models.KeywordIndexType.KEYWORD,
        is_tenant=True,
    ),
)

Tenant optimization is supported for the following datatypes:

keyword
uuid
Principal Index
Available as of v1.11.0

Similar to the tenant index, the principal index is used to optimize storage for faster search, assuming that the search request is primarily filtered by the principal field.

A good example of a use case for the principal index is time-related data, where each point is associated with a timestamp. In this case, the principal index can be used to optimize storage for faster search with time-based filters.

http
python
typescript
rust
java
csharp
go
client.create_payload_index(
    collection_name="{collection_name}",
    field_name="timestamp",
    field_schema=models.IntegerIndexParams(
        type=models.IntegerIndexType.INTEGER,
        is_principal=True,
    ),
)

Principal optimization is supported for following types:

integer
float
datetime
Full-text index
Qdrant supports full-text search for string payload. Full-text index allows you to filter points by the presence of a word or a phrase in the payload field.

Full-text index configuration is a bit more complex than other indexes, as you can specify the tokenization parameters. Tokenization is the process of splitting a string into tokens, which are then indexed in the inverted index.

See Full Text match for examples of querying with a full-text index.

To create a full-text index, you can use the following:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.create_payload_index(
    collection_name="{collection_name}",
    field_name="name_of_the_field_to_index",
    field_schema=models.TextIndexParams(
        type=models.TextIndexType.TEXT,
        tokenizer=models.TokenizerType.WORD,
        min_token_len=2,
        max_token_len=10,
        lowercase=True,
    ),
)

Tokenizers
Tokenizers are algorithms used to split text into smaller units called tokens, which are then indexed and searched in a full-text index. In the context of Qdrant, tokenizers determine how string payloads are broken down for efficient searching and filtering. The choice of tokenizer affects how queries match the indexed text, supporting different languages, word boundaries, and search behaviours such as prefix or phrase matching.

Available tokenizers are:

word (default) - splits the string into words, separated by spaces, punctuation marks, and special characters.
whitespace - splits the string into words, separated by spaces.
prefix - splits the string into words, separated by spaces, punctuation marks, and special characters, and then creates a prefix index for each word. For example: hello will be indexed as h, he, hel, hell, hello.
multilingual - a special type of tokenizer based on multiple packages like charabia and vaporetto to deliver fast and accurate tokenization for a large variety of languages. It allows proper tokenization and lemmatization for multiple languages, including those with non-Latin alphabets and non-space delimiters. See the charabia documentation for a full list of supported languages and normalization options. Note: For the Japanese language, Qdrant relies on the vaporetto project, which has much less overhead compared to charabia, while maintaining comparable performance.
Lowercasing
By default, full-text search in Qdrant is case-insensitive. For example, users can search for the lowercase term tv and find text fields containing the uppercase word TV. Case-insensitivity is achieved by converting both the words in the index and the query terms to lowercase.

Lowercasing is enabled by default. To use case-sensitive full-text search, configure a full-text index with lowercase set to false.

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.create_payload_index(
    collection_name="{collection_name}",
    field_name="name_of_the_field_to_index",
    field_schema=models.TextIndexParams(
        type=models.TextIndexType.TEXT,
        tokenizer=models.TokenizerType.WORD,
        lowercase=False,
    ),
)

ASCII Folding
Available as of v1.16.0

When enabled, ASCII folding converts Unicode characters into their corresponding ASCII equivalents, for example, by removing diacritics. For instance, the character ã is changed into a, ç becomes c, and é is converted to e.

Because ASCII folding is applied to both the words in the index and the query terms, it increases recall. For example, users can search for cafe and also find text fields containing the word café.

ASCII folding is not enabled by default. To enable it, configure a full-text index with ascii_folding set to true.

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.create_payload_index(
    collection_name="{collection_name}",
    field_name="name_of_the_field_to_index",
    field_schema=models.TextIndexParams(
        type=models.TextIndexType.TEXT,
        tokenizer=models.TokenizerType.WORD,
        ascii_folding=True,
    ),
)

Stemmer
A stemmer is an algorithm used in text processing to reduce words to their root or base form, known as the “stem.” For example, the words “running”, “runner and “runs” can all be reduced to the stem “run.” When configuring a full-text index in Qdrant, you can specify a stemmer to be used for a particular language. This enables the index to recognize and match different inflections or derivations of a word.

Qdrant provides an implementation of Snowball stemmer, a widely used and performant variant for some of the most popular languages. For the list of supported languages, please visit the rust-stemmers repository.

For full-text indices, stemming is not enabled by default. To enable it, configure the snowball stemmer with the desired language:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.create_payload_index(
    collection_name="{collection_name}",
    field_name="name_of_the_field_to_index",
    field_schema=models.TextIndexParams(
        type=models.TextIndexType.TEXT,
        tokenizer=models.TokenizerType.WORD,
        stemmer=models.SnowballParams(
            type=models.Snowball.SNOWBALL,
            language=models.SnowballLanguage.ENGLISH
        )
    ),
)

Stopwords
Stopwords are common words (such as “the”, “is”, “at”, “which”, and “on”) that are often filtered out during text processing because they carry little meaningful information for search and retrieval tasks.

In Qdrant, you can specify a list of stopwords to be ignored during full-text indexing and search. This helps simplify search queries and improves relevance.

You can configure stopwords based on predefined languages, as well as extend existing stopword lists with custom words.

For full-text indices, stopword removal is not enabled by default. To enable it, configure the stopwords parameter with the desired languages and any custom stopwords:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

# Simple
client.create_payload_index(
    collection_name="{collection_name}",
    field_name="name_of_the_field_to_index",
    field_schema=models.TextIndexParams(
        type=models.TextIndexType.TEXT,
        tokenizer=models.TokenizerType.WORD,
        stopwords=models.Language.ENGLISH,
    ),
)

# Explicit
client.create_payload_index(
    collection_name="{collection_name}",
    field_name="name_of_the_field_to_index",
    field_schema=models.TextIndexParams(
        type=models.TextIndexType.TEXT,
        tokenizer=models.TokenizerType.WORD,
        stopwords=models.StopwordsSet(
            languages=[
                models.Language.ENGLISH,
                models.Language.SPANISH,
            ],
            custom=[
                "example"
            ]
        ),
    ),
)

Phrase Search
Phrase search in Qdrant allows you to find documents or points where a specific sequence of words appears together, in the same order, within a text payload field. This is useful when you want to match exact phrases rather than individual words scattered throughout the text.

When using a full-text index with phrase search enabled, you can perform phrase search by enclosing the desired phrase in double quotes in your filter query. For example, searching for "machine learning" will only return results where the words “machine” and “learning” appear together as a phrase, not just anywhere in the text.

For efficient phrase search, Qdrant requires building an additional data structure, so it needs to be configured during the creation of the full-text index:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.create_payload_index(
    collection_name="{collection_name}",
    field_name="name_of_the_field_to_index",
    field_schema=models.TextIndexParams(
        type=models.TextIndexType.TEXT,
        tokenizer=models.TokenizerType.WORD,
        lowercase=True,
        phrase_matching=True,
    ),
)

See Phrase Match for examples of querying phrases with a full-text index.

Vector Index
A vector index is a data structure built on vectors through a specific mathematical model. Through the vector index, we can efficiently query several vectors similar to the target vector.

Qdrant currently only uses HNSW as a dense vector index.

HNSW (Hierarchical Navigable Small World Graph) is a graph-based indexing algorithm. It builds a multi-layer navigation structure for an image according to certain rules. In this structure, the upper layers are more sparse and the distances between nodes are farther. The lower layers are denser and the distances between nodes are closer. The search starts from the uppermost layer, finds the node closest to the target in this layer, and then enters the next layer to begin another search. After multiple iterations, it can quickly approach the target position.

In order to improve performance, HNSW limits the maximum degree of nodes on each layer of the graph to m. In addition, you can use ef_construct (when building an index) or ef (when searching targets) to specify a search range.

The corresponding parameters could be configured in the configuration file:

storage:
  # Default parameters of HNSW Index. Could be overridden for each collection or named vector individually
  hnsw_index:
    # Number of edges per node in the index graph.
    # Larger the value - more accurate the search, more space required.
    m: 16
    # Number of neighbours to consider during the index building.
    # Larger the value - more accurate the search, more time required to build index.
    ef_construct: 100
    # Minimal size threshold (in KiloBytes) below which full-scan is preferred over HNSW search.
    # This measures the total size of vectors being queried against.
    # When the maximum estimated amount of points that a condition satisfies is smaller than
    # `full_scan_threshold_kb`, the query planner will use full-scan search instead of HNSW index
    # traversal for better performance.
    # Note: 1Kb = 1 vector of size 256
    full_scan_threshold: 10000

And so in the process of creating a collection. The ef parameter is configured during the search and by default is equal to ef_construct.

HNSW is chosen for several reasons. First, HNSW is well-compatible with the modification that allows Qdrant to use filters during a search. Second, it is one of the most accurate and fastest algorithms, according to public benchmarks.

Available as of v1.1.1

The HNSW parameters can also be configured on a collection and named vector level by setting hnsw_config to fine-tune search performance.

Sparse Vector Index
Available as of v1.7.0

Sparse vectors in Qdrant are indexed with a special data structure, which is optimized for vectors that have a high proportion of zeroes. In some ways, this indexing method is similar to the inverted index, which is used in text search engines.

A sparse vector index in Qdrant is exact, meaning it does not use any approximation algorithms.
All sparse vectors added to the collection are immediately indexed in the mutable version of a sparse index.
With Qdrant, you can benefit from a more compact and efficient immutable sparse index, which is constructed during the same optimization process as the dense vector index.

This approach is particularly useful for collections storing both dense and sparse vectors.

To configure a sparse vector index, create a collection with the following parameters:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.create_collection(
    collection_name="{collection_name}",
    vectors_config={},
    sparse_vectors_config={
        "text": models.SparseVectorParams(
            index=models.SparseIndexParams(on_disk=False),
        )
    },
)

`
The following parameters may affect performance:

on_disk: true - The index is stored on disk, which lets you save memory. This may slow down search performance.
on_disk: false - The index is still persisted on disk, but it is also loaded into memory for faster search.
Unlike a dense vector index, a sparse vector index does not require a predefined vector size. It automatically adjusts to the size of the vectors added to the collection.

Note: A sparse vector index only supports dot-product similarity searches. It does not support other distance metrics.

IDF Modifier
Available as of v1.10.0

For many search algorithms, it is important to consider how often an item occurs in a collection. Intuitively speaking, the less frequently an item appears in a collection, the more important it is in a search.

This is also known as the Inverse Document Frequency (IDF). It is used in text search engines to rank search results based on the rarity of a word in a collection.

IDF depends on the currently stored documents and therefore can’t be pre-computed in the sparse vectors in streaming inference mode. In order to support IDF in the sparse vector index, Qdrant provides an option to modify the sparse vector query with the IDF statistics automatically.

The only requirement is to enable the IDF modifier in the collection configuration:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://localhost:6333")

client.create_collection(
    collection_name="{collection_name}",
    vectors_config={},
    sparse_vectors_config={
        "text": models.SparseVectorParams(
            modifier=models.Modifier.IDF,
        ),
    },
)

Qdrant uses the following formula to calculate the IDF modifier:

 

Where:

N is the total number of documents in the collection.
n is the number of documents containing non-zero values for the given vector element.
Filterable Index
Separately, a payload index and a vector index cannot solve the problem of search using the filter completely.

In the case of high-selectivity (weak) filters, you can use the HNSW index as it is. In the case of low-selectivity (strict) filters, you can use the payload index and complete rescore.

However, for cases in the middle, this approach does not work well. On the one hand, we cannot apply a full scan on too many vectors. On the other hand, the HNSW graph starts to fall apart when using too strict filters.

HNSW fail

Qdrant solves this problem by extending the HNSW graph with additional edges based on the stored payload values. Extra edges allow you to efficiently search for nearby vectors using the HNSW index and apply filters as you search in the graph. You can find more information on this approach in our article.

However, in some cases, these additional edges might not be enough. These extra edges are added per each payload index separately, but not per each possible combination of them. So, a combination of two or more strict filters still might lead to disconnected graph components. The same may happen when having a large number of soft-deleted points in the graph. In such cases, the ACORN Search Algorithm can be used.







Snapshots
Available as of v0.8.4

Snapshots are tar archive files that contain data and configuration of a specific collection on a specific node at a specific time. In a distributed setup, when you have multiple nodes in your cluster, you must create snapshots for each node separately when dealing with a single collection.

This feature can be used to archive data or easily replicate an existing deployment. For disaster recovery, Qdrant Cloud users may prefer to use Backups instead, which are physical disk-level copies of your data.

A collection level snapshot only contains data within that collection, including the collection configuration, all points and payloads. Collection aliases are not included and can be migrated or recovered separately.

For a step-by-step guide on how to use snapshots, see our tutorial.

Create snapshot
If you work with a distributed deployment, you have to create snapshots for each node separately. A single snapshot will contain only the data stored on the node on which the snapshot was created.
To create a new snapshot for an existing collection:

http
python
typescript
rust
java
csharp
go
POST /collections/{collection_name}/snapshots

This is a synchronous operation for which a tar archive file will be generated into the snapshot_path.

Delete snapshot
Available as of v1.0.0

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient

client = QdrantClient(url="http://localhost:6333")

client.delete_snapshot(
    collection_name="{collection_name}", snapshot_name="{snapshot_name}"
)

List snapshot
List of snapshots for a collection:

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient

client = QdrantClient(url="http://localhost:6333")

client.list_snapshots(collection_name="{collection_name}")

Retrieve snapshot
Only available through the REST API for the time being.
To download a specified snapshot from a collection as a file:

http
bash
shell
GET /collections/{collection_name}/snapshots/{snapshot_name}

Restore snapshot
Snapshots generated in one Qdrant cluster can only be restored to other Qdrant clusters that share the same minor version. For instance, a snapshot captured from a v1.4.1 cluster can only be restored to clusters running version v1.4.x, where x is equal to or greater than 1.
Snapshots can be restored in three possible ways:

Recovering from a URL or local file (useful for restoring a snapshot file that is on a remote server or already stored on the node)
Recovering from an uploaded file (useful for migrating data to a new cluster)
Recovering during start-up (useful when running a self-hosted single-node Qdrant instance)
Regardless of the method used, Qdrant will extract the shard data from the snapshot and properly register shards in the cluster. If there are other active replicas of the recovered shards in the cluster, Qdrant will replicate them to the newly recovered node by default to maintain data consistency.

Recover from a URL or local file
Available as of v0.11.3

This method of recovery requires the snapshot file to be downloadable from a URL or exist as a local file on the node (like if you created the snapshot on this node previously). If instead you need to upload a snapshot file, see the next section.

To recover from a URL or local file use the snapshot recovery endpoint. This endpoint accepts either a URL like https://example.com or a file URI like file:///tmp/snapshot-2022-10-10.snapshot. If the target collection does not exist, it will be created.

http
python
typescript
from qdrant_client import QdrantClient

client = QdrantClient(url="http://qdrant-node-2:6333")

client.recover_snapshot(
    "{collection_name}",
    "http://qdrant-node-1:6333/collections/collection_name/snapshots/snapshot-2022-10-10.snapshot",
)

When recovering from a URL, the URL must be reachable by the Qdrant node that you are restoring. In Qdrant Cloud, restoring via URL is not supported since all outbound traffic is blocked for security purposes. You may still restore via file URI or via an uploaded file.
Recover from an uploaded file
The snapshot file can also be uploaded as a file and restored using the recover from uploaded snapshot. This endpoint accepts the raw snapshot data in the request body. If the target collection does not exist, it will be created.

curl -X POST 'http://{qdrant-url}:6333/collections/{collection_name}/snapshots/upload?priority=snapshot' \
    -H 'api-key: ********' \
    -H 'Content-Type:multipart/form-data' \
    -F 'snapshot=@/path/to/snapshot-2022-10-10.snapshot'

This method is typically used to migrate data from one cluster to another, so we recommend setting the priority to “snapshot” for that use-case.

Recover during start-up
This method cannot be used in a multi-node deployment and cannot be used in Qdrant Cloud.
If you have a single-node deployment, you can recover any collection at start-up and it will be immediately available. Restoring snapshots is done through the Qdrant CLI at start-up time via the --snapshot argument which accepts a list of pairs such as <snapshot_file_path>:<target_collection_name>

For example:

./qdrant --snapshot /snapshots/test-collection-archive.snapshot:test-collection --snapshot /snapshots/test-collection-archive.snapshot:test-copy-collection

The target collection must be absent otherwise the program will exit with an error.

If you wish instead to overwrite an existing collection, use the --force_snapshot flag with caution.

Snapshot priority
When recovering a snapshot to a non-empty node, there may be conflicts between the snapshot data and the existing data. The “priority” setting controls how Qdrant handles these conflicts. The priority setting is important because different priorities can give very different end results. The default priority may not be best for all situations.

The available snapshot recovery priorities are:

replica: (default) prefer existing data over the snapshot.
snapshot: prefer snapshot data over existing data.
no_sync: restore snapshot without any additional synchronization.
To recover a new collection from a snapshot, you need to set the priority to snapshot. With snapshot priority, all data from the snapshot will be recovered onto the cluster. With replica priority (default), you’d end up with an empty collection because the collection on the cluster did not contain any points and that source was preferred.

no_sync is for specialized use cases and is not commonly used. It allows managing shards and transferring shards between clusters manually without any additional synchronization. Using it incorrectly will leave your cluster in a broken state.

To recover from a URL, you specify an additional parameter in the request body:

http
bash
python
typescript
from qdrant_client import QdrantClient, models

client = QdrantClient(url="http://qdrant-node-2:6333")

client.recover_snapshot(
    "{collection_name}",
    "http://qdrant-node-1:6333/collections/{collection_name}/snapshots/snapshot-2022-10-10.snapshot",
    priority=models.SnapshotPriority.SNAPSHOT,
)

Snapshots for the whole storage
Available as of v0.8.5

Sometimes it might be handy to create snapshot not just for a single collection, but for the whole storage, including collection aliases. Qdrant provides a dedicated API for that as well. It is similar to collection-level snapshots, but does not require collection_name.

Full storage snapshots are only suitable for single-node deployments. Distributed mode is not supported as it doesn't contain the necessary files for that.
Full storage snapshots can be created and downloaded from Qdrant Cloud, but you cannot restore a Qdrant Cloud cluster from a whole storage snapshot since that requires use of the Qdrant CLI. You can use Backups instead.
Create full storage snapshot
http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient

client = QdrantClient(url="http://localhost:6333")

client.create_full_snapshot()

Delete full storage snapshot
Available as of v1.0.0

http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient

client = QdrantClient(url="http://localhost:6333")

client.delete_full_snapshot(snapshot_name="{snapshot_name}")

List full storage snapshots
http
python
typescript
rust
java
csharp
go
from qdrant_client import QdrantClient

client = QdrantClient("localhost", port=6333)

client.list_full_snapshots()

Download full storage snapshot
Only available through the REST API for the time being.
GET /snapshots/{snapshot_name}

Restore full storage snapshot
Restoring snapshots can only be done through the Qdrant CLI at startup time.

For example:

./qdrant --storage-snapshot /snapshots/full-snapshot-2022-07-18-11-20-51.snapshot

Storage
Created, uploaded and recovered snapshots are stored as .snapshot files. By default, they’re stored on the local file system. You may also configure to use an S3 storage service for them.

Local file system
By default, snapshots are stored at ./snapshots or at /qdrant/snapshots when using our Docker image.

The target directory can be controlled through the configuration:

storage:
  # Specify where you want to store snapshots.
  snapshots_path: ./snapshots

Alternatively you may use the environment variable QDRANT__STORAGE__SNAPSHOTS_PATH=./snapshots.

Available as of v1.3.0

While a snapshot is being created, temporary files are placed in the configured storage directory by default. In case of limited capacity or a slow network attached disk, you can specify a separate location for temporary files:

storage:
  # Where to store temporary files
  temp_path: /tmp

S3
Available as of v1.10.0

Rather than storing snapshots on the local file system, you may also configure to store snapshots in an S3-compatible storage service. To enable this, you must configure it in the configuration file.

For example, to configure for AWS S3:

storage:
  snapshots_config:
    # Use 's3' to store snapshots on S3
    snapshots_storage: s3

    s3_config:
      # Bucket name
      bucket: your_bucket_here

      # Bucket region (e.g. eu-central-1)
      region: your_bucket_region_here

      # Storage access key
      # Can be specified either here or in the `QDRANT__STORAGE__SNAPSHOTS_CONFIG__S3_CONFIG__ACCESS_KEY` environment variable.
      access_key: your_access_key_here

      # Storage secret key
      # Can be specified either here or in the `QDRANT__STORAGE__SNAPSHOTS_CONFIG__S3_CONFIG__SECRET_KEY` environment variable.
      secret_key: your_secret_key_here

      # S3-Compatible Storage URL
      # Can be specified either here or in the `QDRANT__STORAGE__SNAPSHOTS_CONFIG__S3_CONFIG__ENDPOINT_URL` environment variable.
      endpoint_url: your_url_here

Apart from Snapshots, Qdrant also provides the Qdrant Migration Tool that supports:

Migration between Qdrant Cloud instances.
Migrating vectors from other providers into Qdrant.
Migrating from Qdrant OSS to Qdrant Cloud.
Follow our migration guide to learn how to effectively use the Qdrant Migration tool.